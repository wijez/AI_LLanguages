# chat/views.py
from typing import List, Dict
from asgiref.sync import async_to_sync
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import NotFound
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiParameter, OpenApiTypes, OpenApiResponse

from languages.models import Topic
from chat.models import Conversation, Turn, TopicKnowledge
from chat.serializers import TopicSerializer, ConversationSerializer, StartPayloadSerializer, MessagePayloadSerializer
from chat.services.llm import build_system_prompt, call_llm
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from chat.rag.retriever import Retriever, format_rag_snippet

class TopicViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Topic.objects.all().order_by('id')
    serializer_class = TopicSerializer
    permission_classes = [AllowAny]

class ChatViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Chat"],
        summary="Start a conversation",
        request=StartPayloadSerializer,
        responses={201: ConversationSerializer},
        parameters=[
            OpenApiParameter(
                name="dry_run",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Chỉ dựng system prompt, không lưu DB"
            ),
            OpenApiParameter(
                name="X-Debug",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=False,
                description="Bật debug tuỳ biến cho request này"
            ),
        ],
        examples=[
            OpenApiExample(
                "Start roleplay với RAG, khoanh theo skill",
                value={
                    "topic_slug": "a1-greetings",
                    "mode": "roleplay",
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
                    "conv_name": "Buổi luyện chào hỏi #1"
                },
                request_only=True,
            ),
        ],
    )
    @action(detail=False, methods=['post'], url_path='start')
    def start(self, request):
        s = StartPayloadSerializer(data=request.data); s.is_valid(raise_exception=True); data = s.validated_data
        # 1) find topic
        if data.get('topic_id'):
            topic = get_object_or_404(Topic, id=data['topic_id'])
        elif data.get('topic_slug'):
            topic = get_object_or_404(Topic, slug=data['topic_slug'])
        else:
            title = data.get('topic_title')
            if not title:
                raise NotFound({"error":"TOPIC_NOT_FOUND","message":"Thiếu topic_id/slug/title"})
            lang = data.get('language_override') or 'vi'
            try:
                topic = Topic.objects.get(title=title, language=topic.language if hasattr(topic,'language') else lang)
            except Topic.DoesNotExist:
                raise NotFound({"error":"TOPIC_NOT_FOUND","message":f"Không tìm thấy Topic title='{title}'"})

        overrides = data.get('roleplay_overrides') or {}
        roleplay = {**(getattr(topic, "roleplay_preset", {}) or {}), **overrides}
        roleplay.update({
            "temperature": data.get("temperature", 0.7),
            "max_tokens": data.get("max_tokens", 512),
            "suggestions_count": data.get("suggestions_count", 2),
            "use_rag": data.get("use_rag", False),
            "knowledge_limit": data.get("knowledge_limit", 3),
        })
        effective_lang = data.get("language_override") or getattr(topic, "language", "vi")

        # (optional) knowledge tĩnh theo topic
        rag_snippet = ""
        if roleplay.get("use_rag"):
            items = list(TopicKnowledge.objects.filter(topic=topic).order_by('id')[:roleplay["knowledge_limit"]])
            if items:
                rag_snippet = "\n\n".join([f"- {it.title}: {it.content[:600]}" for it in items])

        base_system = build_system_prompt(topic={"title": topic.title, "language": effective_lang}, mode=data.get('mode','free'), roleplay=roleplay)
        system_prompt = base_system + (f"\n\n[Knowledge]\n{rag_snippet}" if rag_snippet else "")

        with transaction.atomic():
            conv = Conversation.objects.create(topic=topic, roleplay=roleplay)
            Turn.objects.create(conversation=conv, role='system', content=system_prompt)

        return Response(ConversationSerializer(conv).data, status=status.HTTP_201_CREATED)

    @extend_schema(tags=["Chat"], summary="Send a message",
                   request=MessagePayloadSerializer, responses={200: OpenApiResponse(response=ConversationSerializer)})
    @action(detail=False, methods=['post'], url_path='message')
    def message(self, request):
        s = MessagePayloadSerializer(data=request.data); s.is_valid(raise_exception=True)
        conv = get_object_or_404(Conversation, id=s.validated_data['conv_id'])
        user_text = s.validated_data['user_text']
        Turn.objects.create(conversation=conv, role='user', content=user_text)

        # lấy 10 turn gần nhất
        history_qs = conv.turns.all().order_by('-id')[:10]
        history: List[Dict[str,str]] = [{"role": t.role, "content": t.content} for t in reversed(list(history_qs))]
        system = next((t['content'] for t in history if t['role']=='system'), '')

        # RAG động
        roleplay = conv.roleplay or {}
        if roleplay.get("use_rag"):
            try:
                from chat.rag.retriever import Retriever, format_rag_snippet
                retr = Retriever.ensure()
                hits = retr.search(user_text, topic=conv.topic.slug, k=roleplay.get("knowledge_limit", 3))
                rag_snip = format_rag_snippet(hits)
                if rag_snip:
                    system = system + f"\n\n[RAG Context]\n{rag_snip}\n\nHãy ưu tiên thông tin trong [RAG Context] khi trả lời."
            except Exception:
                pass

        try:
            llm = async_to_sync(call_llm)(system, history, user_text)
        except Exception as e:
            llm = {"text": f"(llm error) {e}", "meta": {"suggestions": [], "confidence": 0.0}}

        Turn.objects.create(conversation=conv, role='assistant', content=llm.get('text',''), meta=llm.get('meta', {}))
        conv.refresh_from_db()
        return Response({'reply': llm.get('text',''), 'meta': llm.get('meta', {}), 'conversation': ConversationSerializer(conv).data})


class RAGSearchView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        q = request.query_params.get("q", "")
        topic = request.query_params.get("topic")
        skill = request.query_params.get("skill")
        retr = Retriever.ensure()
        hits = retr.search(q, topic=topic, skill=skill, k=5)
        return Response({
            "q": q, "topic": topic, "skill": skill,
            "results": [{"score": s, "meta": m, "doc": d} for s, m, d in hits],
            "snippet": format_rag_snippet(hits),
        })