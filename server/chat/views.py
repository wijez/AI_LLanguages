import asyncio
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from .models import Conversation, Turn
from languages.models import Topic
from .serializers import (
    StartRequestSerializer, StartResponseSerializer,
    MessageRequestSerializer, MessageResponseSerializer,
    ConversationSerializer
)
from .utils import simple_reply  # vẫn giữ làm fallback
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes, OpenApiExample

# NEW: LLM bridge
from .services.llm import call_llm, stream_llm_sync, build_system_prompt    
from django.http import StreamingHttpResponse


def _turns_to_history(conv):
    """
    Trả về list[dict] các turn (user/assistant) theo thứ tự thời gian tăng dần
    để feed vào LLM.
    """
    qs = (Turn.objects
          .filter(conversation=conv)
          .exclude(role='system')
          .order_by('created_at')
          .values('role', 'content'))
    return list(qs)


class ChatViewSet(viewsets.ViewSet):
    authentication_classes = []
    permission_classes = []

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
                    "roleplay": {"role": "trợ giảng"},  # <- nếu bạn muốn
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
            # Gợi ý: có thể lưu mode/roleplay vào Conversation nếu bạn có field
        )

        # Dựng system prompt từ topic + mode + roleplay
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
        examples=[
            OpenApiExample(
                "Message example",
                value={
                    "conv_id": "c13a62c2-e7d0-449c-bc09-a0c4d98b6f05",
                    "user_text": "Hello! How are you?",
                    "expect_text": "Nice to meet you.",
                    "force_pron": True
                },
                request_only=True,
            ),
            OpenApiExample(
                "Response example",
                value={
                    "reply": "Tốt lắm! Bạn có thể thử nói: 'Good morning'?",
                    "meta": {
                        "suggestions": ["Thử nói 'Good morning' chậm và rõ."],
                        "confidence": 0.7,
                        "pron": {
                            "force_pron": True,
                            "expect_text": "Good morning",
                            "score_endpoint": "/api/pron/score/"
                        }
                    },
                    "conversation": {
                        "id": "c13a62c2-e7d0-449c-bc09-a0c4d98b6f05",
                        "topic": {"id": 1, "slug": "a1-greetings", "title": "A1 - Basic Greetings"}
                    }
                },
                response_only=True,
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
        history = _turns_to_history(conv)

        # --- call LLM (no premature use of llm_res) ---
        try:
            llm_res = asyncio.run(call_llm(
                system_prompt, history, user_text or "",
                options={
                    "temperature": float(conv.temperature or 0.4),
                    "num_ctx": int(conv.max_tokens or 300)
                }
            ))
            reply_text = (llm_res.get("text") or "").strip()
            suggestions = (llm_res.get("meta") or {}).get("suggestions") or []
            if not reply_text:
                # graceful fallback if empty
                reply_text, suggestions = simple_reply(conv.topic.title, user_text)
                reply_text += "\n\n(Lưu ý: LLM trả rỗng)"
        except Exception as e:
            reply_text, suggestions = simple_reply(conv.topic.title, user_text)
            reply_text += f"\n\n(Lưu ý: fallback LLM: {e})"

        # --- persist assistant turn ---
        assistant_meta = {
            'suggestions': suggestions,
            'confidence': 0.7,
            'pron': {
                'expect_text': reply_text,
                'score_endpoint': '/api/speech/pron/score/',
                'tts_endpoint': '/api/speech/tts/'
            }
        }
        Turn.objects.create(conversation=conv, role='assistant', content=reply_text, meta=assistant_meta)

        # Optional: include a few recent turns if requested
        conv_ser = ConversationSerializer(conv).data
        try:
            limit = int(request.query_params.get('return_turns') or 0)
        except ValueError:
            limit = 0
        if limit > 0:
            recent_turns = list(
                Turn.objects.filter(conversation=conv).order_by('-created_at')[:limit]
            )
            recent_turns = list(reversed(recent_turns))
            conv_ser['recent_turns'] = [
                {"role": t.role, "content": t.content, "meta": t.meta, "created_at": t.created_at}
                for t in recent_turns
            ]

        resp = {'reply': reply_text, 'meta': assistant_meta, 'conversation': conv_ser}
        return Response(resp, status=status.HTTP_200_OK)
    @extend_schema(
        tags=["Chat"],
        summary="Streaming AI reply (NDJSON)",
        description="Trả về NDJSON stream: {delta}, {meta}, {type}…",
        request=MessageRequestSerializer,
        parameters=[
            OpenApiParameter(
                name="return_turns", type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY, required=False,
                description="Số lượt hội thoại gần nhất cần gửi vào LLM (mặc định 6)."
            ),
        ],
        examples=[
            OpenApiExample(
                "Request",
                value={"conv_id":"...-uuid-...", "user_text":"Hi there!"},
                request_only=True
            ),
            OpenApiExample(
                "NDJSON Response (stream)",
                value=[
                    {"type":"start"},
                    {"delta":"Xin "},
                    {"delta":"chào bạn!"},
                    {"meta":{"suggestions":["..."],"confidence":0.7}},
                    {"type":"done"},
                ],
                response_only=True
            ),
        ],
    )
    @action(detail=False, methods=["post"])
    def stream(self, request):
        """
        POST /api/chat/chat/stream/
        Body: { conv_id, user_text }
        Trả NDJSON stream chunks: delta/meta/done.
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
        history_qs = (Turn.objects
                      .filter(conversation=conv)
                      .exclude(role="system")
                      .order_by("created_at")
                      .values("role", "content"))
        history = list(history_qs)[-6:]  # lấy 6 lượt gần nhất

        def gen():
            yield from stream_llm_sync(
                system_prompt, history, user_text,
                options={
                    "temperature": float(conv.temperature or 0.4),
                    "num_ctx": 1536,
                    "num_predict": 160,
                    "keep_alive": "15m",
                },
            )

        resp = StreamingHttpResponse(gen(), content_type="application/x-ndjson; charset=utf-8")
        resp["Cache-Control"] = "no-cache"
        # nếu có Nginx:
        # resp["X-Accel-Buffering"] = "no"
        return resp