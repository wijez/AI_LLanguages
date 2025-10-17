from django.db import transaction
from rest_framework import viewsets, mixins, status, permissions
from drf_spectacular.utils import extend_schema, OpenApiExample
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from django.db.models import F
from django.utils.dateparse import parse_datetime

from utils.permissions import HasInternalApiKey, IsAdminOrSuperAdmin
from rest_framework.permissions import AllowAny, IsAuthenticated

from languages.models import (
    Language, Lesson, LanguageEnrollment, Topic,
    TopicProgress, Skill, UserSkillStats, LessonSkill
)
from languages.serializers import (
    AutoGenerateLessonsIn, AutoGenerateLessonsOut, LanguageSerializer, LanguageEnrollmentSerializer, TopicProgressSerializer, TopicSerializer,
    SkillSerializer, LessonSerializer, UserSkillStatsSerializer, LanguageEnrollmentExportSerializer,
    SkillStatsSerializer, LessonSkillSerializer
)
from rest_framework.viewsets import ReadOnlyModelViewSet


class LanguageViewSet(viewsets.ModelViewSet):
    queryset = Language.objects.all()
    serializer_class = LanguageSerializer

    def create(self, request, *args, **kwargs):
        is_many = isinstance(request.data, list)
        serializer = self.get_serializer(data=request.data, many=is_many)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)  
        return Response(serializer.data, status=status.HTTP_201_CREATED)



class LanguageEnrollmentViewSet(viewsets.ModelViewSet):
    queryset = LanguageEnrollment.objects.all()
    serializer_class = LanguageEnrollmentSerializer


# ---- SỬA LẠI CHO B2: Lesson select_related("topic"), filter theo through ----
class LessonViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminOrSuperAdmin]
    queryset = Lesson.objects.select_related("topic").order_by("order", "id")
    serializer_class = LessonSerializer

    def get_queryset(self):
        qs = super().get_queryset()

        # ?skill_id= → lọc qua bảng nối
        skill_id = self.request.query_params.get("skill_id")
        if skill_id:
            qs = qs.filter(lessonskill__skill_id=skill_id)

        # ?topic=slug hoặc id
        t = self.request.query_params.get("topic")
        if t:
            if t.isdigit():
                qs = qs.filter(topic_id=int(t))
            else:
                qs = qs.filter(topic__slug=t)
        return qs

    # (tuỳ chọn) endpoint lấy skills của 1 lesson theo thứ tự
    @action(detail=True, methods=['get'], url_path='skills')
    def skills(self, request, pk=None):
        qs = (Skill.objects
              .filter(lessonskill__lesson_id=pk, is_active=True)
              .annotate(ls_order=F('lessonskill__order'))
              .order_by('ls_order', 'id'))
        return Response(SkillSerializer(qs, many=True).data)


class TopicViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminOrSuperAdmin]
    queryset = Topic.objects.select_related("language").all()
    serializer_class = TopicSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        lang = self.request.query_params.get('lang')
        if lang:
            qs = qs.filter(language__abbreviation=lang)
        return qs

    def get_serializer_class(self):
        # DÙNG serializer khác cho action custom
        if getattr(self, "action", None) == "auto_generate_lessons":
            return AutoGenerateLessonsIn
        return super().get_serializer_class()

    def create(self, request, *args, **kwargs):
        many = isinstance(request.data, list)
        serializer = self.get_serializer(data=request.data, many=many)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        if many:
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    # ---- Lấy skills theo topic qua lessons (distinct) ----
    @action(detail=True, methods=['get'], url_path='skills')
    def skills(self, request, pk=None):
        qs = (Skill.objects
              .filter(lessons__topic_id=pk, is_active=True)
              .distinct()
              .order_by('title', 'id'))
        return Response(SkillSerializer(qs, many=True, context=self.get_serializer_context()).data)
    
    @action(detail=False, methods=['post'], url_path='auto-generate-lessons')
    def auto_generate_lessons(self, request):
        # parse & validate payload bằng serializer riêng
        in_ser = self.get_serializer(data=request.data)
        in_ser.is_valid(raise_exception=True)
        per = in_ser.validated_data.get("per_topic", 5)
        langs = in_ser.validated_data.get("langs")
        reset = in_ser.validated_data.get("reset", False)

        qs = self.get_queryset()
        if langs:
            qs = qs.filter(language__abbreviation__in=langs)

        topics_count = qs.count()
        created = 0
        with transaction.atomic():
            for topic in qs:
                if reset:
                    Lesson.objects.filter(topic=topic).delete()

                existing = set(Lesson.objects.filter(topic=topic).values_list("order", flat=True))
                to_create = []
                for i in range(1, per + 1):
                    if i in existing:
                        continue
                    is_review = (i == per)
                    to_create.append(Lesson(
                        topic=topic,
                        title=f"{topic.title} · {'Review' if is_review else f'Lesson {i}'}",
                        content={"type": "review"} if is_review else {"type": "lesson", "unit": i},
                        order=i,
                        xp_reward=15 if is_review else 10,
                        duration_seconds=180 if is_review else 120,
                    ))
                if to_create:
                    Lesson.objects.bulk_create(to_create)
                    created += len(to_create)

        # trả response đúng schema
        out = AutoGenerateLessonsOut({"created": created, "topics": topics_count})
        return Response(out.data, status=status.HTTP_201_CREATED)


# ---- SỬA LẠI CHO B2: Skill không còn topic/order; filter theo lessons__topic ----
class SkillViewSet(mixins.ListModelMixin,
                   mixins.CreateModelMixin,
                   mixins.UpdateModelMixin,
                   mixins.DestroyModelMixin,
                   mixins.RetrieveModelMixin,
                   viewsets.GenericViewSet):
    permission_classes = [IsAdminOrSuperAdmin]
    queryset = Skill.objects.filter(is_active=True).order_by("id")
    serializer_class = SkillSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        # ?topic= slug hoặc id
        t = self.request.query_params.get("topic")
        if t:
            if t.isdigit():
                qs = qs.filter(lessons__topic_id=int(t))
            else:
                qs = qs.filter(lessons__topic__slug=t)
            qs = qs.distinct()
        # ?type=
        ty = self.request.query_params.get("type")
        if ty:
            qs = qs.filter(type=ty)
        return qs

    # GET /api/skills/{id}/lessons/ → theo LessonSkill.order
    @action(detail=True, methods=["get"], url_path="lessons")
    def lessons(self, request, pk=None):
        qs = (Lesson.objects
              .filter(lessonskill__skill_id=pk)
              .annotate(skill_order=F('lessonskill__order'))
              .select_related("topic")
              .order_by("skill_order", "id"))
        return Response(LessonSerializer(qs, many=True).data)


class UserSkillStatsViewSet(viewsets.ModelViewSet):
    permission_classes = [HasInternalApiKey | IsAuthenticated]
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


# ---- SỬA LẠI CHO B2: export_chat_training không còn l.skill/topic → duyệt từng skill ----
@api_view(["GET"])
def export_chat_training(request):
    """
    Gộp blocks thành JSONL để chatbot build RAG nhanh.
    Duyệt mỗi Lesson, và cho mỗi Skill thuộc lesson đó, tạo item theo Lesson.content (nếu có).
    """
    import json
    from django.http import StreamingHttpResponse

    topics = request.GET.get("topics")
    qs_topic = Topic.objects.filter(slug__in=topics.split(",")) if topics else Topic.objects.all()
    lessons = Lesson.objects.filter(topic__in=qs_topic).prefetch_related("skills", "topic")

    def gen():
        for l in lessons:
            blocks = (l.content or {}).get("blocks", [])
            for idx, b in enumerate(blocks, start=1):
                # tạo 1 item cho MỖI skill của lesson
                for s in l.skills.all():
                    item = {
                        "topic": l.topic.slug,
                        "skill": s.title,
                        "skill_type": s.type,
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


# ---- SỬA LẠI CHO B2: bỏ select_related/topic/order không tồn tại, thay order an toàn ----
class SkillStatsViewSet(ReadOnlyModelViewSet):
    """
    GET /api/skill_stats/?user_id=42&language=en
    Trả về danh sách skill stats của user trong ngôn ngữ chỉ định.
    """
    serializer_class = SkillStatsSerializer
    permission_classes = [HasInternalApiKey | IsAuthenticated]

    def get_queryset(self):
        qs = (UserSkillStats.objects
              .select_related("enrollment__language", "enrollment__user", "skill"))

        user_id = self.request.query_params.get("user_id")
        lang = self.request.query_params.get("language")
        if user_id:
            qs = qs.filter(enrollment__user_id=user_id)
        if lang:
            qs = qs.filter(enrollment__language__abbreviation=lang)

        # không còn "skill__topic__order"/"skill__order"
        return qs.order_by("skill__title", "skill_id")


class TopicProgressViewSet(viewsets.ModelViewSet):
    """
    /api/topic_progress/                -> list (lọc theo user/lang/topic/enrollment)
    /api/topic_progress/{id}/           -> retrieve/update/patch/delete

    Actions:
    - POST /api/topic_progress/upsert/  -> tạo/cập nhật theo (user, language, topic)
    - POST /api/topic_progress/{id}/add_xp/          {"amount": 10}
    - POST /api/topic_progress/{id}/mark_complete/
    - POST /api/topic_progress/{id}/set_reviewable/  {"value": true}
    """
    permission_classes = [HasInternalApiKey | IsAuthenticated]
    serializer_class = TopicProgressSerializer
    queryset = (
        TopicProgress.objects
        .select_related("topic", "enrollment", "enrollment__user", "enrollment__language")
        .all()
    )

    def get_queryset(self):
        qs = (TopicProgress.objects
              .select_related("topic",
                              "enrollment",
                              "enrollment__user",
                              "enrollment__language")
              .all())

        user_id = self.request.query_params.get("user_id")
        enrollment_id = self.request.query_params.get("enrollment_id")
        language = self.request.query_params.get("language")   # abbreviation, vd: en
        topic = self.request.query_params.get("topic")         # id hoặc slug

        if enrollment_id:
            qs = qs.filter(enrollment_id=enrollment_id)

        if user_id:
            qs = qs.filter(enrollment__user_id=user_id)

        if language:
            qs = qs.filter(enrollment__language__abbreviation=language)

        if topic:
            if topic.isdigit():
                qs = qs.filter(topic_id=int(topic))
            else:
                qs = qs.filter(topic__slug=topic)

        # Sắp xếp gợi ý: theo topic.order nếu cần (Topic có field order)
        qs = qs.order_by("topic__order", "topic_id", "id")
        return qs

    @action(detail=False, methods=["post"], url_path="upsert")
    def upsert(self, request):
        """
        Body:
        {
          "user_id": 1,
          "language": "en",
          "topic": 12 | "a1-greetings",
          "defaults": { "xp": 20, "completed": false, "reviewable": false }
        }
        - Tìm/ tạo LanguageEnrollment(user, language)
        - Tìm topic theo id hoặc slug
        - get_or_create TopicProgress(enrollment, topic), update defaults nếu có
        """
        data = request.data or {}
        user_id = data.get("user_id")
        lang_abbr = data.get("language")
        topic_ref = data.get("topic")
        defaults = data.get("defaults", {})

        if not user_id or not lang_abbr or topic_ref is None:
            return Response(
                {"detail": "Missing user_id / language / topic"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            lang = Language.objects.get(abbreviation=lang_abbr)
        except Language.DoesNotExist:
            return Response({"detail": f"Language '{lang_abbr}' not found"}, status=400)

        # enrollment
        enrollment, _ = LanguageEnrollment.objects.get_or_create(
            user_id=user_id, language=lang,
            defaults={"total_xp": 0, "streak_days": 0}
        )

        # topic
        if isinstance(topic_ref, int) or (isinstance(topic_ref, str) and topic_ref.isdigit()):
            topic_obj = Topic.objects.get(id=int(topic_ref))
        else:
            topic_obj = Topic.objects.get(slug=str(topic_ref))

        tp, created = TopicProgress.objects.get_or_create(
            enrollment=enrollment,
            topic=topic_obj,
            defaults={
                "xp": defaults.get("xp", 0),
                "completed": defaults.get("completed", False),
                "reviewable": defaults.get("reviewable", False),
            }
        )

        # Nếu đã tồn tại → update các trường trong defaults (nếu có gửi)
        updated = False
        for f in ("xp", "completed", "reviewable"):
            if f in defaults and getattr(tp, f) != defaults[f]:
                setattr(tp, f, defaults[f])
                updated = True
        if updated:
            tp.save()

        ser = self.get_serializer(tp)
        return Response({"created": created, "obj": ser.data}, status=201 if created else 200)

    @action(detail=True, methods=["post"], url_path="add_xp")
    def add_xp(self, request, pk=None):
        amount = request.data.get("amount", 0)
        try:
            amount = int(amount)
        except Exception:
            return Response({"detail": "amount must be integer"}, status=400)
        if amount == 0:
            return Response({"detail": "amount must be non-zero"}, status=400)

        tp = self.get_object()
        tp.xp = (tp.xp or 0) + amount
        tp.save(update_fields=["xp"])
        return Response({"id": tp.id, "xp": tp.xp})

    @action(detail=True, methods=["post"], url_path="mark_complete")
    def mark_complete(self, request, pk=None):
        tp = self.get_object()
        if not tp.completed:
            tp.completed = True
            tp.save(update_fields=["completed"])
        return Response({"id": tp.id, "completed": tp.completed})

    @action(detail=True, methods=["post"], url_path="set_reviewable")
    def set_reviewable(self, request, pk=None):
        val = request.data.get("value")
        if isinstance(val, bool) is False:
            return Response({"detail": "value must be boolean"}, status=400)
        tp = self.get_object()
        tp.reviewable = val
        tp.save(update_fields=["reviewable"])
        return Response({"id": tp.id, "reviewable": tp.reviewable})
