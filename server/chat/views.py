import json
import asyncio
from typing import Optional, List, Dict, Any
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.http import HttpResponseBadRequest, StreamingHttpResponse

from .models import Conversation, Turn
from languages.models import Topic
from .serializers import (
    StartRequestSerializer, StartResponseSerializer,
    MessageRequestSerializer, MessageResponseSerializer,
    ConversationSerializer
)
from .utils import simple_reply
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes, OpenApiExample
from .rag.retriever import Retriever, format_rag_snippet
from .services.llm import call_llm, stream_llm_sync, build_system_prompt   


# ---- history helper (thêm last_n) ----
def _turns_to_history(conv, last_n: Optional[int] = None) -> List[Dict[str, str]]:
    """
    Trả về list[dict] các turn (user/assistant) theo thứ tự thời gian tăng dần.
    Nếu last_n được set, chỉ lấy N lượt gần nhất để tối ưu độ trễ.
    """
    qs = (Turn.objects
          .filter(conversation=conv)
          .exclude(role='system')
          .order_by('created_at')
          .values('role', 'content'))
    rows = list(qs)
    if last_n and last_n > 0:
        # mỗi lượt gồm 1 user + 1 assistant (thường), nhưng để đơn giản: cắt theo count mẫu tin
        rows = rows[-last_n:]
    return rows


class ChatViewSet(viewsets.ViewSet):
    authentication_classes = []
    permission_classes = []
    serializer_class = ConversationSerializer

    @extend_schema(
        tags=["Chat"],
        summary="Start a conversation",
        description=(
            "Mở một phiên chat theo topic có sẵn. "
            "Hỗ trợ các tham số mở rộng như mode, roleplay, rag_skill, rag_k, skill_title, "
            "system_extra, language_override, conv_name."
        ),
        request=StartRequestSerializer,
        responses={201: StartResponseSerializer},
        examples=[
            OpenApiExample(
                "Start example",
                value={
                    "topic_slug": "a1-greetings",
                    "mode": "roleplay",
                    "roleplay": {"role": "trợ giảng"},
                    "temperature": 0.4,
                    "max_tokens": 300,
                    "suggestions_count": 2,
                    "use_rag": True,
                    "knowledge_limit": 3,
                    "rag_skill": "Hello & Goodbye",
                    "rag_k": 5,
                    "skill_title": "Hello & Goodbye",
                    "system_extra": "Ưu tiên luyện câu chào lịch sự.",
                    "language_override": "vi",
                    "conv_name": "Buổi luyện chào hỏi #1",
                },
                request_only=True,
            )
        ],
    )
    @action(detail=False, methods=['post'])
    def start(self, request):
        s = StartRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        topic = get_object_or_404(Topic, slug=data['topic_slug'])

        conv = Conversation.objects.create(
            topic=topic,
            use_rag=data.get('use_rag', True),
            temperature=data.get('temperature', 0.4),
            max_tokens=data.get('max_tokens', 300),
            suggestions_count=data.get('suggestions_count', 2),
            knowledge_limit=data.get('knowledge_limit', 3),
        )

        topic_dict = {"title": topic.title, "language": data.get('language_override', 'en')}
        system_prompt = build_system_prompt(
            topic=topic_dict,
            mode=data.get('mode', 'roleplay'),
            roleplay=data.get('roleplay', {}) or {}
        )
        if data.get('system_extra'):
            system_prompt += f"\nGhi chú: {data['system_extra']}"

        Turn.objects.create(conversation=conv, role='system', content=system_prompt, meta={})

        payload = {
            'conversation': conv,
            'topic': topic,
            'turns': list(Turn.objects.filter(conversation=conv).order_by('created_at')),
        }
        return Response(StartResponseSerializer(payload).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["Chat"],
        summary="Send message / get AI reply (LLM)",
        description=(
            "Gửi tin nhắn theo conv_id, server gọi LLM (Ollama) với system+history. "
            "Có thể truyền expect_text + force_pron để UI hiển thị yêu cầu đọc và chấm phát âm."
        ),
        request=MessageRequestSerializer,
        responses={200: MessageResponseSerializer},
        parameters=[
            OpenApiParameter(
                name="return_turns",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Số lượt hội thoại gần nhất cần trả về cùng response."
            ),
        ],
    )
    @action(detail=False, methods=['post'])
    def message(self, request):
        s = MessageRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data

        conv = get_object_or_404(Conversation, id=v['conv_id'])
        user_text = v.get('user_text') or ""

        if user_text.strip():
            Turn.objects.create(conversation=conv, role='user', content=user_text, meta={})

        system_turn = Turn.objects.filter(conversation=conv, role='system').first()
        system_prompt = system_turn.content if system_turn else ""

        # limit history nếu có query param
        try:
            last_n = int(request.query_params.get('return_turns') or 0)
        except ValueError:
            last_n = 0
        history = _turns_to_history(conv, last_n=last_n)

        # --- RAG: chỉ chèn khi có hit ---
        rag_hits = []
        ctx = ""
        if bool(getattr(conv, "use_rag", False)):
            try:
                rag = Retriever.ensure()
                rag_hits = rag.search(
                    query=(user_text or "").strip() or getattr(conv.topic, "title", ""),
                    topic=getattr(conv.topic, "slug", None),
                    skill=(request.data.get("skill") or None),
                    k=int(getattr(conv, "knowledge_limit", 3) or 3),
                )
                ctx = format_rag_snippet(rag_hits) if rag_hits else ""
                if ctx:
                    system_prompt = (system_prompt or "") + (
                        "\n\n[REFERENCE MATERIALS]\n" + ctx +
                        "\n(Hãy ưu tiên dựa trên tài liệu trên khi phản hồi.)"
                    )
            except Exception:
                pass

        # --- Gọi LLM (non-stream) ---
        try:
            llm_res = asyncio.run(call_llm(
                system_prompt, history, user_text or "",
                options={
                    "temperature": float(getattr(conv, "temperature", 0.4) or 0.4),
                    # đúng mapping: số token sinh ra → num_predict
                    "num_predict": int(getattr(conv, "max_tokens", 300) or 300),
                    # context window để model "đọc" prompt + context
                    "num_ctx": 1536,
                }
            ))
            reply_text = (llm_res.get("text") or "").strip()
            suggestions = (llm_res.get("meta") or {}).get("suggestions") or []
            if not reply_text:
                reply_text, suggestions = simple_reply(conv.topic.title, user_text)
                reply_text += "\n\n(Lưu ý: LLM trả rỗng)"
        except Exception as e:
            reply_text, suggestions = simple_reply(conv.topic.title, user_text)
            reply_text += f"\n\n(Lưu ý: fallback LLM: {e})"

        assistant_meta = {
            "suggestions": suggestions,
            "confidence": 0.7,
            "rag": {
                "used": bool(rag_hits),
                "hits": [
                    {"score": float(s), "meta": m, "doc": d}
                    for (s, m, d) in (rag_hits[: int(getattr(conv, "knowledge_limit", 3) or 3)] if rag_hits else [])
                ],
            },
            "pron": {
                "expect_text": reply_text,
                "score_endpoint": "/api/speech/pron/score/",
                "tts_endpoint": "/api/speech/tts/",
            },
        }
        Turn.objects.create(conversation=conv, role='assistant', content=reply_text, meta=assistant_meta)

        conv_ser = ConversationSerializer(conv).data
        if last_n and last_n > 0:
            recent_turns = list(
                Turn.objects.filter(conversation=conv).order_by('-created_at')[:last_n]
            )
            recent_turns = list(reversed(recent_turns))
            conv_ser["recent_turns"] = [
                {"role": t.role, "content": t.content, "meta": t.meta, "created_at": t.created_at}
                for t in recent_turns
            ]

        resp = {"reply": reply_text, "meta": assistant_meta, "conversation": conv_ser}
        return Response(resp, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Chat"],
        summary="Streaming AI reply (NDJSON)",
        description="Trả về NDJSON stream: {rag?}, {start}, {delta}*, {meta}, {done}. Đồng thời lưu Turn assistant sau khi stream xong.",
        request=MessageRequestSerializer,
        parameters=[
            OpenApiParameter(
                name="return_turns", type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY, required=False,
                description="Số message gần nhất đưa vào LLM (mặc định 6)."
            ),
        ],
    )
    @action(detail=False, methods=["post"])
    def stream(self, request):
        """
        POST /api/chat/chat/stream/
        Body: { conv_id, user_text[, skill] }
        Trả NDJSON: (rag)?, start, delta*, meta, done.
        """
        s = MessageRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        conv_id = s.validated_data["conv_id"]
        user_text = s.validated_data.get("user_text") or ""

        conv = get_object_or_404(Conversation, id=conv_id)

        if user_text:
            Turn.objects.create(conversation=conv, role="user", content=user_text, meta={})

        system_turn = Turn.objects.filter(conversation=conv, role="system").order_by("created_at").first()
        system_prompt = system_turn.content if system_turn else ""

        # limit history để giảm độ trễ (mặc định 6)
        try:
            last_n = int(request.query_params.get('return_turns') or 6)
        except ValueError:
            last_n = 6
        history = _turns_to_history(conv, last_n=last_n)

        # --- RAG: tính trước để client render nguồn sớm ---
        rag_hits = []
        ctx = ""
        if bool(getattr(conv, "use_rag", False)):
            try:
                rag = Retriever.ensure()
                rag_hits = rag.search(
                    query=(user_text or "").strip() or getattr(conv.topic, "title", ""),
                    topic=getattr(conv.topic, "slug", None),
                    skill=(request.data.get("skill") or None),
                    k=int(getattr(conv, "knowledge_limit", 3) or 3),
                )
                ctx = format_rag_snippet(rag_hits) if rag_hits else ""
            except Exception:
                pass

        final_system_prompt = (system_prompt + "\n\n[REFERENCE MATERIALS]\n" + ctx) if ctx else system_prompt

        def gen():
            # 1) Gửi RAG hits ngay đầu stream (nếu có)
            if rag_hits:
                yield (json.dumps({
                    "type": "rag",
                    "hits": [
                        {"score": float(s), "meta": m, "doc": d}
                        for (s, m, d) in rag_hits[: int(getattr(conv, "knowledge_limit", 3) or 3)]
                    ]
                }, ensure_ascii=False) + "\n").encode("utf-8")

            # 2) Stream token từ LLM + thu thập để lưu Turn
            reply_parts: List[str] = []
            captured_meta: Dict[str, Any] | None = None

            for chunk in stream_llm_sync(
                final_system_prompt, history, user_text,
                options={
                    "temperature": float(getattr(conv, "temperature", 0.4) or 0.4),
                    "num_ctx": 1536,  # context window
                    "num_predict": int(getattr(conv, "max_tokens", 300) or 300),  # số token sinh
                    "keep_alive": "15m",
                },
            ):
                # bắt NDJSON để tích lũy
                try:
                    sline = chunk.decode("utf-8") if isinstance(chunk, (bytes, bytearray)) else str(chunk)
                    line = sline.strip()
                    if line:
                        obj = json.loads(line)
                        if "delta" in obj and obj["delta"]:
                            reply_parts.append(obj["delta"])
                        elif "meta" in obj and obj["meta"]:
                            captured_meta = obj["meta"]
                except Exception:
                    pass

                # forward chunk ra client
                yield chunk

            # 3) Sau khi stream xong → lưu Turn assistant
            reply_text = "".join(reply_parts).strip()
            meta_payload = captured_meta or {"suggestions": ["Bạn muốn đi sâu phần nào tiếp?"], "confidence": 0.7}
            assistant_meta = {
                **meta_payload,
                "rag": {
                    "used": bool(rag_hits),
                    "hits": [
                        {"score": float(s), "meta": m, "doc": d}
                        for (s, m, d) in (rag_hits[: int(getattr(conv, "knowledge_limit", 3) or 3)] if rag_hits else [])
                    ],
                },
                "pron": {
                    "expect_text": reply_text,
                    "score_endpoint": "/api/speech/pron/score/",
                    "tts_endpoint": "/api/speech/tts/",
                },
            }
            if reply_text:
                Turn.objects.create(conversation=conv, role="assistant", content=reply_text, meta=assistant_meta)

        resp = StreamingHttpResponse(gen(), content_type="application/x-ndjson; charset=utf-8")
        resp["Cache-Control"] = "no-cache"
        resp["X-Accel-Buffering"] = "no"
        return resp

    @action(detail=False, methods=['post'])
    def reindex(self, request):
        from django.contrib.admin.views.decorators import staff_member_required
        from django.utils.decorators import method_decorator
        @method_decorator(staff_member_required)
        def _do(_req):
            from .rag.indexer import harvest_docs
            from .rag.embedders import make_embedder
            from django.conf import settings
            import json, numpy as np
            from pathlib import Path
            docs, metas = harvest_docs(None)
            X = make_embedder().encode(docs)
            out = Path(settings.RAG_INDEX_DIR); out.mkdir(parents=True, exist_ok=True)
            (out / "docs.json").write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
            (out / "metas.json").write_text(json.dumps(metas, ensure_ascii=False), encoding="utf-8")
            np.save(out / "embeddings.npy", X.astype("float32"))
            return Response({"ok": True, "count": len(docs)})
        return _do(request)
    