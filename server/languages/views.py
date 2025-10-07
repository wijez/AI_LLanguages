from django.shortcuts import render
from rest_framework import viewsets, mixins, status
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema, OpenApiExample
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from vocabulary.models import KnownWord
from languages.models import ( 
    Language, Lesson, LanguageEnrollment, Topic, 
    TopicProgress, Skill, UserSkillStats
)
from languages.serializers import (
    LanguageSerializer, LanguageEnrollmentSerializer, TopicProgressSerializer, TopicSerializer,
    SkillSerializer, LessonSerializer, UserSkillStatsSerializer, LanguageEnrollmentExportSerializer
)

class LanguageViewSet(viewsets.ModelViewSet):
    queryset = Language.objects.all()
    serializer_class = LanguageSerializer

    @action(detail=False, methods=['post'], url_path='bulk')
    def bulk_create(self, request):
        if not isinstance(request.data, list):
            return Response({"detail": "Expected a list of objects."},
                            status=status.HTTP_400_BAD_REQUEST)

        ser = LanguageSerializer(data=request.data, many=True)
        ser.is_valid(raise_exception=True)

        # upsert theo abbreviation (giả định là unique)
        created_or_existing = []
        for item in ser.validated_data:
            obj, _ = Language.objects.get_or_create(
                abbreviation=item["abbreviation"],
                defaults=item
            )
            # nếu đã tồn tại và muốn cập nhật thêm field:
            # for k, v in item.items(): setattr(obj, k, v); obj.save(update_fields=item.keys())
            created_or_existing.append(obj)

        return Response(LanguageSerializer(created_or_existing, many=True).data,
                        status=status.HTTP_201_CREATED)


class LanguageEnrollmentViewSet(viewsets.ModelViewSet):
    queryset = LanguageEnrollment.objects.all()
    serializer_class = LanguageEnrollmentSerializer


class LessonViewSet(viewsets.ModelViewSet):
    queryset = Lesson.objects.select_related("skill", "skill__topic").order_by("id")
    serializer_class = LessonSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        skill_id = self.request.query_params.get("skill_id")
        if skill_id:
            qs = qs.filter(skill_id=skill_id)
        tslug = self.request.query_params.get("topic")
        if tslug:
            qs = qs.filter(skill__topic__slug=tslug)
        return qs


class TopicViewSet(viewsets.ModelViewSet):
    queryset = Topic.objects.all()
    serializer_class = TopicSerializer

    def create(self, request, *args, **kwargs):
        # Hỗ trợ cả single (dict) và bulk (list)
        many = isinstance(request.data, list)
        serializer = self.get_serializer(data=request.data, many=many)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data if not many else None)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class TopicSkillViewSet(mixins.ListModelMixin,
                   mixins.RetrieveModelMixin,
                   mixins.CreateModelMixin,            # <-- thêm mixin tạo mới
                   viewsets.GenericViewSet):
    queryset = Topic.objects.select_related("language").all().order_by("order","id")
    serializer_class = TopicSerializer

    def get_serializer_class(self):
        # dùng serializer khác khi POST
        if self.request and self.request.method == "POST":
            return TopicSerializer
        return TopicSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        lang = self.request.query_params.get("lang")
        if lang:
            qs = qs.filter(language__abbreviation=lang)
        ua = self.request.query_params.get("updated_after")
        if ua:
            dt = parse_datetime(ua)
            if dt:
                qs = qs.filter(created_at__gte=dt)
        return qs

    @extend_schema(
        tags=["Topics"],
        summary="Create a Topic",
        request=TopicSerializer,
        responses={201: TopicSerializer},
        examples=[
            OpenApiExample(
                "Create topic",
                value={
                    "slug": "a1-greetings",
                    "title": "A1 - Basic Greetings",
                    "description": "Learn simple greetings, introductions, and polite expressions.",
                    "language": 1,          # id của Language
                    "order": 1
                },
                request_only=True
            )
        ]
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @action(detail=True, methods=["get"])
    def skills(self, request, pk=None):
        topic = self.get_object()
        skills = Skill.objects.filter(topic=topic).order_by("order","id")
        return Response(SkillSerializer(skills, many=True).data)


class TopicProgressViewSet(viewsets.ModelViewSet):
    queryset = TopicProgress.objects.all()
    serializer_class = TopicProgressSerializer


class SkillViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = Skill.objects.select_related("topic").all().order_by("order","id")
    serializer_class = SkillSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        tslug = self.request.query_params.get("topic")
        if tslug:
            qs = qs.filter(topic__slug=tslug)
        return qs

    @action(detail=True, methods=["get"])
    def lessons(self, request, pk=None):
        lessons = Lesson.objects.filter(skill_id=pk).order_by("id")
        return Response(LessonSerializer(lessons, many=True).data)


class UserSkillStatsViewSet(viewsets.ModelViewSet):
    queryset = UserSkillStats.objects.all()
    serializer_class = UserSkillStatsSerializer


@api_view(['GET'])
def export_learning_data(request):
    enrollments = LanguageEnrollment.objects.all().prefetch_related(
        "skill_stats__skill",
        "known_words__word",
        "topic_progress__topic",
        "language"
    )
    serializer = LanguageEnrollmentExportSerializer(enrollments, many=True)
    return Response({"enrollments": serializer.data})


@api_view(["GET"])
def export_chat_training(request):
    """Gộp blocks thành JSONL để chatbot build RAG nhanh."""
    import json
    from django.http import StreamingHttpResponse
    topics = request.GET.get("topics")
    qs_topic = Topic.objects.filter(slug__in=topics.split(",")) if topics else Topic.objects.all()
    lessons = Lesson.objects.filter(skill__topic__in=qs_topic).select_related("skill","skill__topic")
    def gen():
        for l in lessons:
            blocks = (l.content or {}).get("blocks", [])
            for idx, b in enumerate(blocks, start=1):
                item = {
                    "topic": l.skill.topic.slug,
                    "skill": l.skill.title,
                    "lesson": l.title,
                    "lesson_id": l.id,
                    "block_index": idx,
                    "block_type": b.get("type"),
                    "prompt": b.get("prompt") or json.dumps(b, ensure_ascii=False),
                    "expected": b.get("answer") or b.get("target") or "",
                    "meta": b
                }
                yield json.dumps(item, ensure_ascii=False) + "\n"
    resp = StreamingHttpResponse(gen(), content_type="application/x-ndjson; charset=utf-8")
    resp["Content-Disposition"] = 'inline; filename="chat_training.jsonl"'
    return resp


