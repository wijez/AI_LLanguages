import json
import asyncio
from typing import Optional, List, Dict, Any
from .rag.retriever import get_index 

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.http import StreamingHttpResponse

from .models import Conversation, Turn
from languages.models import Topic, Skill  
from .serializers import (
    StartRequestSerializer, StartResponseSerializer,
    MessageRequestSerializer, MessageResponseSerializer,
    ConversationSerializer
)
from .utils import simple_reply
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes, OpenApiExample
from .rag.retriever import get_index  
from .services.llm import call_llm, stream_llm_sync, build_system_prompt


# ---- helpers ----
def _turns_to_history(conv, last_n: Optional[int] = None) -> List[Dict[str, str]]:
    qs = (Turn.objects
          .filter(conversation=conv)
          .exclude(role='system')
          .order_by('created_at')
          .values('role', 'content'))
    rows = list(qs)
    if last_n and last_n > 0:
        rows = rows[-last_n:]
    return rows


def _format_rag_snippet(hits: List[Dict], max_items: int = 3, max_len: int = 350) -> str:
    """
    hits: [{"text": "...", "score": float, "meta": {...}}, ...]
    Trả về chuỗi context gọn cho system prompt.
    """
    out = []
    for i, h in enumerate(hits[:max_items], start=1):
        txt = (h.get("text") or "").strip()
        if len(txt) > max_len:
            txt = txt[:max_len].rsplit(" ", 1)[0] + "…"
        meta = h.get("meta") or {}
        tag = f"{meta.get('topic_slug','?')} / L{meta.get('lesson_order','?')} / {meta.get('skill_title','?')}"
        out.append(f"[{i}] ({h.get('score',0):.3f}) {tag}: {txt}")
    return "\n".join(out)


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

        topic_dict = {
            "title": topic.title,
            "language": data.get('language_override', getattr(topic.language, "abbreviation", "en"))
        }
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
        ),
        request=MessageRequestSerializer,
        responses={200: MessageResponseSerializer},
        examples=[
            OpenApiExample(
                "Ask with RAG + force_pron",
                value={
                    "conv_id": "7f7f2e35-2a8c-4f0a-8121-5f8b4d2a6f12",
                    "user_text": "How to greet politely?",
                    "skill": "Hello & Goodbye",
                    "force_pron": "true",
                    "expect_text": "Good morning! Nice to meet you."
                },
                request_only=True,
            )
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

        # history
        try:
            last_n = int(request.query_params.get('return_turns') or 0)
        except ValueError:
            last_n = 0
        history = _turns_to_history(conv, last_n=last_n)

        # ---- RAG
        rag_hits = []
        ctx = ""
        if bool(getattr(conv, "use_rag", False)):
            try:
                idx = get_index()
                k = int(getattr(conv, "knowledge_limit", 3) or 3)
                lang_abbr = getattr(conv.topic.language, "abbreviation", None)
                topic_slug = getattr(conv.topic, "slug", None)

                # Ưu tiên skill_id, fallback skill (title)
                skill_ids = None
                if isinstance(v.get("skill_id"), int):
                    skill_ids = [v["skill_id"]]
                elif isinstance(v.get("skill"), str) and v["skill"].strip():
                    qs = Skill.objects.filter(title__iexact=v["skill"].strip())
                    if lang_abbr:
                        qs = qs.filter(language_code=lang_abbr)
                    skill_ids = list(qs.values_list("id", flat=True))[:1] or None

                rag_hits = idx.search(
                    query=(user_text or "").strip() or getattr(conv.topic, "title", ""),
                    top_k=k,
                    language=lang_abbr,
                    topics=[topic_slug] if topic_slug else None,
                    skills=skill_ids,
                ) or []

                if rag_hits:
                    ctx = _format_rag_snippet(rag_hits, max_items=k)
                    system_prompt = (system_prompt or "") + (
                        "\n\n[REFERENCE MATERIALS]\n" + ctx +
                        "\n(Hãy ưu tiên dựa trên tài liệu trên khi phản hồi.)"
                    )
            except Exception:
                pass

        # ---- LLM
        try:
            llm_res = asyncio.run(call_llm(
                system_prompt, history, user_text or "",
                options={
                    "temperature": float(getattr(conv, "temperature", 0.4) or 0.4),
                    "num_predict": int(getattr(conv, "max_tokens", 300) or 300),
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

        # ---- Pron meta: ưu tiên expect_text client cung cấp khi force_pron=True
        expect_for_pron = (v.get("expect_text") or "").strip()
        if v.get("force_pron", False):
            # nếu client không đưa expect_text thì dùng reply_text
            expect_for_pron = expect_for_pron or reply_text

        assistant_meta = {
            "suggestions": suggestions,
            "confidence": 0.7,
            "rag": {
                "used": bool(rag_hits),
                "hits": [
                    {"score": float(h.get("score", 0.0)), "meta": h.get("meta"), "doc": h.get("text")}
                    for h in rag_hits[: int(getattr(conv, "knowledge_limit", 3) or 3)]
                ],
            },
            "pron": {
                # nếu force_pron thì expect_text sẽ là văn bản yêu cầu user đọc;
                # nếu không, vẫn để reply_text 
                "expect_text": expect_for_pron or reply_text,
                "force": bool(v.get("force_pron", False)),
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

        return Response({"reply": reply_text, "meta": assistant_meta, "conversation": conv_ser}, status=200)

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
        s = MessageRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        conv_id = s.validated_data["conv_id"]
        user_text = s.validated_data.get("user_text") or ""

        conv = get_object_or_404(Conversation, id=conv_id)

        if user_text:
            Turn.objects.create(conversation=conv, role="user", content=user_text, meta={})

        system_turn = Turn.objects.filter(conversation=conv, role="system").order_by("created_at").first()
        system_prompt = system_turn.content if system_turn else ""

        try:
            last_n = int(request.query_params.get('return_turns') or 6)
        except ValueError:
            last_n = 6
        history = _turns_to_history(conv, last_n=last_n)

        rag_hits = []
        ctx = ""
        if bool(getattr(conv, "use_rag", False)):
            try:
                idx = get_index()
                k = int(getattr(conv, "knowledge_limit", 3) or 3)
                lang_abbr = getattr(conv.topic.language, "abbreviation", None)
                topic_slug = getattr(conv.topic, "slug", None)

                skill_ids: List[int] | None = None
                skill_id = request.data.get("skill_id")
                if isinstance(skill_id, int):
                    skill_ids = [skill_id]
                else:
                    skill_title = request.data.get("skill")
                    if isinstance(skill_title, str) and skill_title.strip():
                        qs_skill = Skill.objects.filter(title__iexact=skill_title.strip())
                        if lang_abbr:
                            qs_skill = qs_skill.filter(language_code=lang_abbr)
                        skill_ids = list(qs_skill.values_list("id", flat=True))[:1] or None

                res = idx.search(
                    query=(user_text or "").strip() or getattr(conv.topic, "title", ""),
                    top_k=k,
                    language=lang_abbr,
                    topics=[topic_slug] if topic_slug else None,
                    skills=skill_ids,
                )
                rag_hits = res or []
                if rag_hits:
                    ctx = _format_rag_snippet(rag_hits, max_items=k)
            except Exception:
                pass

        final_system_prompt = (system_prompt + "\n\n[REFERENCE MATERIALS]\n" + ctx) if ctx else system_prompt

        def gen():
            # 1) đẩy RAG hits sớm để client render nguồn
            if rag_hits:
                yield (json.dumps({
                    "type": "rag",
                    "hits": [
                        {"score": float(h.get("score", 0.0)), "meta": h.get("meta"), "doc": h.get("text")}
                        for h in rag_hits[: int(getattr(conv, "knowledge_limit", 3) or 3)]
                    ]
                }, ensure_ascii=False) + "\n").encode("utf-8")

            reply_parts: List[str] = []
            captured_meta: Dict[str, Any] | None = None

            for chunk in stream_llm_sync(
                final_system_prompt, history, user_text,
                options={
                    "temperature": float(getattr(conv, "temperature", 0.4) or 0.4),
                    "num_ctx": 1536,
                    "num_predict": int(getattr(conv, "max_tokens", 300) or 300),
                    "keep_alive": "15m",
                },
            ):
                # Thu NDJSON để lưu turn
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

                yield chunk

            reply_text = "".join(reply_parts).strip()
            meta_payload = captured_meta or {"suggestions": ["Bạn muốn đi sâu phần nào tiếp?"], "confidence": 0.7}
            assistant_meta = {
                **meta_payload,
                "rag": {
                    "used": bool(rag_hits),
                    "hits": [
                        {"score": float(h.get("score", 0.0)), "meta": h.get("meta"), "doc": h.get("text")}
                        for h in rag_hits[: int(getattr(conv, "knowledge_limit", 3) or 3)]
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

    @extend_schema(
        tags=["Chat"],
        summary="(Admin) Rebuild RAG index",
        description="Thu hoạch → embed → lưu index; có thể lọc theo topics/langs.",
        request=OpenApiTypes.OBJECT,
        responses={201: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=['post'], permission_classes=[IsAdminUser], url_path='reindex')
    def reindex(self, request):
        """
        Body (tuỳ chọn):
        {
          "topics": ["a1-greetings", "basics-1"],
          "langs":  ["en", "vi"]
        }
        """
        from .rag import indexer
        body = request.data or {}
        topics = body.get("topics")
        langs = body.get("langs")
        res = indexer.build_index(topic_slugs=topics, langs=langs)
        return Response(res, status=status.HTTP_201_CREATED)
