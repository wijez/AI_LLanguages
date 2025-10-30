from django.db import transaction
from rest_framework import viewsets, mixins, status, permissions
from drf_spectacular.utils import (
    extend_schema, OpenApiExample, OpenApiResponse
)
from drf_spectacular.types import OpenApiTypes
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from django.db.models import F, Max, Prefetch
from django.utils.text import slugify
from django.utils.dateparse import parse_datetime
from django.shortcuts import get_object_or_404


from utils.permissions import HasInternalApiKey, IsAdminOrSuperAdmin
from rest_framework.permissions import AllowAny, IsAuthenticated

from languages.models import *
from languages.serializers import *
from rest_framework.viewsets import ReadOnlyModelViewSet
from vocabulary.models import Mistake, LearningInteraction
from learning.models import LessonSession
from languages.services.embed_pipeline import embed_blocks
from languages.services.rag import retrieve_blocks, ask_gemini
from languages.services.roleplay_flow import ordered_blocks, split_prologue_and_dialogue
from languages.services.ai_speaker import ai_lines_for
from languages.services.session_mem import create_session, get_session, save_session
from languages.services.validate_turn import score_user_turn, make_hint


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
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = LanguageEnrollmentSerializer
    lookup_field = "pk"
    queryset = LanguageEnrollment.objects.select_related("language").all()
    def get_queryset(self):
        qs = (LanguageEnrollment.objects
                .select_related("language")
                .filter(user=self.request.user)
                .order_by("-created_at"))
        
        abbr = (
            self.request.query_params.get("abbreviation")
            or self.request.query_params.get("language_abbr")
            or self.request.query_params.get("language_code")
            or self.request.query_params.get("code")
        )
        if abbr: 
            qs = qs.filter(language__abbreviation_iexact=abbr)
        
        lang_id = (
            self.request.query_params.get("language_id")
            or self.request.query_params.get("language")
        )
        if lang_id:
            qs = qs.filter(language_id=lang_id)
        return qs.order_by("-created_at")
    

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        obj = serializer.save()
        data = self.get_serializer(obj).data
        created = bool(serializer.context.get("__created__"))
        return Response({"created": created, "enrollment": data},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="me")
    def me(self, request):
        qs = self.get_queryset()
        return Response(self.get_serializer(qs, many=True).data)


class LessonViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminOrSuperAdmin]
    queryset = Lesson.objects.select_related("topic", "topic__language").all()
    serializer_class = LessonSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        skill_id = self.request.query_params.get("skill_id")
        if skill_id:
            qs = qs.filter(lessonskill__skill_id=skill_id)

        t = self.request.query_params.get("topic")
        if t:
            if t.isdigit():
                qs = qs.filter(topic_id=int(t))
            else:
                qs = qs.filter(topic__slug=t)
        return qs

    @action(detail=True, methods=["post"], url_path="add-skill",
        permission_classes=[permissions.IsAuthenticated])
    def add_skill(self, request, pk=None):
        lesson = self.get_object()
        many = isinstance(request.data, list)
        items = request.data if many else [request.data]

        out = []
        with transaction.atomic():
            current = LessonSkill.objects.filter(lesson=lesson).aggregate(m=Max("order"))["m"] or 0
            for raw in items:
                order = raw.pop("order", None)

                # Tạo skill theo schema mới (nested fields):
                ser = SkillSerializer(data=raw, context=self.get_serializer_context())
                ser.is_valid(raise_exception=True)
                skill = ser.save()

                # Tạo bản ghi nối và set order
                if order is None:
                    current += 1
                    order = current
                LessonSkill.objects.create(lesson=lesson, skill=skill, order=order)

                out.append(SkillSerializer(skill, context=self.get_serializer_context()).data)

        return Response(out if many else out[0], status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path='skills',
            permission_classes=[permissions.IsAuthenticated])
    def skills(self, request, pk=None):
        """
        - 200: Trả danh sách skills của lesson theo thứ tự (rỗng nếu chưa có).
        - 404: Lesson không tồn tại.
        """
        # self.get_object() để DRF tự raise 404 nếu lesson sai
        self.get_object()
        qs = (Skill.objects
              .filter(lessonskill__lesson_id=pk, is_active=True)
              .annotate(ls_order=F('lessonskill__order'))
              .order_by('ls_order', 'id'))
        return Response(SkillSerializer(qs, many=True).data)


class TopicViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminOrSuperAdmin]
    queryset = Topic.objects.select_related("language").all()
    serializer_class = TopicSerializer

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:  # GET/HEAD/OPTIONS
            return [permissions.AllowAny()]
        return [IsAdminOrSuperAdmin()]

    def get_queryset(self):
        qs = super().get_queryset()
        abbr = (
            self.request.query_params.get("language_abbr")
            or self.request.query_params.get("abbr")
            or self.request.query_params.get("language_code")
            or self.request.query_params.get("code")
            or self.request.query_params.get("lang")
        )
        if abbr:
            qs = qs.filter(language__abbreviation__iexact=abbr)
        lang = self.request.query_params.get('lang')
        if lang:
            qs = qs.filter(language__abbreviation=lang)
        return qs.order_by("order", "id")

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
    @action(detail=False, methods=['get'], url_path='by-language', permission_classes=[permissions.IsAuthenticated])
    def by_language(self, request):
        user = request.user
        abbr = (
            request.query_params.get("language_abbr")
            or request.query_params.get("abbr")
            or request.query_params.get("language_code")
            or request.query_params.get("code")
            or request.query_params.get("lang")
        )
        lang_id = request.query_params.get("language_id")
        # trả những topic mà user đăng kí 
        qs = Topic.objects.select_related("language").filter(
            language__enrollments__user=user
        )

        if abbr:
            qs = qs.filter(language__abbreviation__iexact=abbr)
            if not LanguageEnrollment.objects.filter(user=user, language__abbreviation__iexact=abbr).exists():
                return Response({"detail": "Not enrolled in this language."}, status=403)

        if lang_id:
            qs = qs.filter(language_id=lang_id)
            # chặn truy cập nếu chưa enroll lang_id:
            if not LanguageEnrollment.objects.filter(user=user, language_id=lang_id).exists():
                return Response({"detail": "Not enrolled in this language."}, status=403)

        qs = qs.order_by("order", "id")

        page = self.paginate_queryset(qs)
        ser = self.get_serializer(page if page is not None else qs, many=True)
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)
    @action(detail=True, methods=['get'], url_path='lessons')
    def lessons(self, request, pk=None):
        """
        GET /api/topics/{id}/lessons/?include_skills=1
        - Mặc định: trả list lesson theo order
        - include_skills=1: trả kèm nested skills (đúng thứ tự trong lesson)
        """
        include_skills = str(request.query_params.get("include_skills", "0")) in ("1", "true", "yes")

        qs = (Lesson.objects
              .filter(topic_id=pk)
              .order_by("order", "id"))

        if include_skills:
            qs = qs.prefetch_related(
                Prefetch(
                    "skills",
                    queryset=(Skill.objects
                              .filter(is_active=True, lessonskill__lesson_id=models.OuterRef("pk"))
                              .annotate(ls_order=F("lessonskill__order"))
                              .order_by("ls_order", "id"))
                )
            )
            ser = LessonWithSkillsSerializer(qs, many=True, context=self.get_serializer_context())
        else:
            ser = LessonLiteSerializer(qs, many=True, context=self.get_serializer_context())

        return Response(ser.data)

# ---- SỬA LẠI CHO B2: Skill không còn topic/order; filter theo lessons__topic ----
class SkillViewSet(mixins.ListModelMixin,
                   mixins.CreateModelMixin,
                   mixins.UpdateModelMixin,
                   mixins.DestroyModelMixin,
                   mixins.RetrieveModelMixin,
                   viewsets.GenericViewSet):
    permission_classes = [IsAdminOrSuperAdmin]
    serializer_class = SkillSerializer

    def _base_queryset(self):
        """
        Queryset có đầy đủ prefetch để trả nested nhanh, tránh N+1.
        Nếu muốn nhẹ hơn ở trang list, có thể bỏ bớt prefetch theo nhu cầu.
        """
        return (
            Skill.objects.filter(is_active=True)
            .select_related("reading_content")
            .prefetch_related(
                Prefetch("quiz_questions",
                         queryset=SkillQuestion.objects
                         .prefetch_related("choices")
                         .order_by("id")),
                Prefetch("fillgaps",
                         queryset=SkillGap.objects.order_by("id")),
                Prefetch("ordering_items",
                         queryset=OrderingItem.objects.order_by("order_index", "id")),
                Prefetch("matching_pairs",
                         queryset=MatchingPair.objects.order_by("id")),
                Prefetch("listening_prompts",
                         queryset=ListeningPrompt.objects.order_by("id")),
                Prefetch("pronunciation_prompts",
                         queryset=PronunciationPrompt.objects.order_by("id")),
                Prefetch("reading_questions",
                         queryset=ReadingQuestion.objects.order_by("id")),
                Prefetch("writing_questions",
                         queryset=WritingQuestion.objects.order_by("id")),
                Prefetch("speaking_prompts",                     
                         queryset=SpeakingPrompt.objects.order_by("id")),
            )
            .order_by("id")
        )

    queryset = None  

    def get_queryset(self):
        qs = self._base_queryset()

        # ?topic= (id hoặc slug) qua M2M LessonSkill: lessons__topic__
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

        # lọc theo lesson_id + sắp xếp theo LessonSkill.order
        lesson = self.request.query_params.get("lesson")
        if lesson:
            qs = qs.filter(lessonskill__lesson_id=lesson) \
                .annotate(ls_order=F("lessonskill__order")) \
                .order_by("ls_order", "id")

        return qs

    def create(self, request, *args, **kwargs):
        """
        Tạo Skill kèm lesson_id (tùy chọn) và order (tùy chọn).
        Body: { ...Skill fields..., "lesson_id": 123, "order": 5? }
        """
        data = request.data.copy()
        lesson_id = data.pop("lesson_id", None)
        order = data.pop("order", None)

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            skill = serializer.save()

            # Gắn vào LessonSkill nếu gửi lesson_id
            if lesson_id is not None:
                try:
                    lesson = Lesson.objects.get(pk=lesson_id)
                except Lesson.DoesNotExist:
                    raise serializers.ValidationError({"lesson_id": f"Lesson {lesson_id} not found."})

                if order is None:
                    current = LessonSkill.objects.filter(lesson=lesson).aggregate(m=Max("order"))["m"] or 0
                    order = current + 1

                LessonSkill.objects.create(lesson=lesson, skill=skill, order=order)

        headers = self.get_success_headers(serializer.data)
        return Response(self.get_serializer(skill).data, status=status.HTTP_201_CREATED, headers=headers)

    # GET /api/skills/{id}/lessons/ → theo LessonSkill.order
    @action(detail=True, methods=["get"], url_path="lessons")
    def lessons(self, request, pk=None):
        qs = (
            Lesson.objects
            .filter(lessonskill__skill_id=pk)
            .annotate(skill_order=F("lessonskill__order"))
            .select_related("topic")
            .order_by("skill_order", "id")
        )
        return Response(LessonSerializer(qs, many=True).data)

    # GET /api/skills/{id}/questions/ → chỉ trả phần câu hỏi/đáp án của skill
    @action(detail=True, methods=["get"], url_path="questions")
    def questions(self, request, pk=None):
        skill = self.get_object()
        data = SkillSerializer(skill).data
        # chỉ giữ các key liên quan tới câu hỏi
        keep_keys = {
            "id", "type",
            "quiz_questions", "fillgaps", "ordering_items", "matching_pairs",
            "listening_prompts", "pronunciation_prompts",
            "reading_content", "reading_questions",
            "writing_questions",
        }
        slim = {k: v for k, v in data.items() if k in keep_keys}
        return Response(slim, status=200)

    # POST|PATCH /api/skills/{id}/upsert-questions/ → ghi đè/ghép bộ câu hỏi (nested payload)
    @action(detail=True, methods=["post", "patch"], url_path="upsert-questions")
    def upsert_questions(self, request, pk=None):
        """
        Payload ví dụ (quiz):
        {
          "quiz_questions": [
            {
              "question_text": "How do you say 'Xin chào' in English?",
              "answer": "Hello",
              "choices": [{"text":"Thanks"},{"text":"Hello"},{"text":"Bye"}]
            }
          ]
        }
        Các loại khác: fillgaps / ordering_items / matching_pairs / listening_prompts /
                       pronunciation_prompts / reading_content / reading_questions / writing_questions
        """
        skill = self.get_object()
        serializer = SkillSerializer(skill, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=["post"], url_path="bulk-create")
    def bulk_create(self, request):
        payload = request.data
        if isinstance(payload, list):
            items = payload
            strict = True
        elif isinstance(payload, dict) and "items" in payload:
            items = payload.get("items") or []
            strict = bool(payload.get("strict", True))
        else:
            return Response(
                {"detail": "Payload must be a list or {items:[...], strict?:bool}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(items, list) or not items:
            return Response({"detail": "items must be a non-empty list"}, status=status.HTTP_400_BAD_REQUEST)

        created, errors = [], []

        def _save_all():
            for i, raw in enumerate(items, start=1):
                data = dict(raw)
                lesson_id = data.pop("lesson_id", None)
                order = data.pop("order", None)

                ser = self.get_serializer(data=data, context=self.get_serializer_context())
                if not ser.is_valid():
                    errors.append({"index": i, "errors": ser.errors})
                    if strict:
                        raise serializers.ValidationError({"detail": "Bulk aborted (strict)", "errors": errors})
                    continue

                try:
                    with transaction.atomic():
                        skill = ser.save()

                        if lesson_id is not None:
                            try:
                                lesson = Lesson.objects.get(pk=lesson_id)
                            except Lesson.DoesNotExist:
                                raise serializers.ValidationError({"lesson_id": f"Lesson {lesson_id} not found."})

                            if order is None:
                                current = LessonSkill.objects.filter(lesson=lesson).aggregate(m=Max("order"))["m"] or 0
                                order_local = current + 1
                            else:
                                order_local = order

                            LessonSkill.objects.create(lesson=lesson, skill=skill, order=order_local)

                        created.append({
                            "id": skill.id,     # <-- giữ int
                            "title": skill.title,
                            "type": skill.type,
                            "lesson_id": lesson_id,
                            "order": order
                        })

                except serializers.ValidationError as e:
                    errors.append({"index": i, "errors": e.detail})
                    if strict:
                        raise

        if strict:
            with transaction.atomic():
                _save_all()
        else:
            _save_all()

        status_code = (
            status.HTTP_201_CREATED if created and not errors else
            (status.HTTP_207_MULTI_STATUS if created and errors else status.HTTP_400_BAD_REQUEST)
        )
        # Trả full bản ghi đã tạo (nested)
        full = Skill.objects.filter(id__in=[c["id"] for c in created])
        return Response({"created": SkillSerializer(full, many=True).data, "errors": errors}, status=status_code)


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
        topic = self.request.query_params.get("topic") 
        mine  = self.request.query_params.get("mine")       

        if mine:
            qs = qs.filter(enrollment__user=self.request.user)
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
    @action(detail=False, methods=["get"], url_path="gate", permission_classes=[IsAuthenticated])
    def gate(self, request):
        """
        Trả về unlock_order cho user hiện tại theo topic (id/slug) + language (abbr, optional).
        - Nếu chưa có TopicProgress → tự tạo với highest_completed_order=0.
        """
        topic_ref = request.query_params.get("topic")
        lang_abbr = request.query_params.get("language")  # optional, giúp xác định enrollment đúng khi 1 user học nhiều ngôn ngữ
        if not topic_ref:
            return Response({"detail": "topic is required (id or slug)."}, status=400)

        # Resolve topic
        try:
            if str(topic_ref).isdigit():
                topic = Topic.objects.select_related("language").get(id=int(topic_ref))
            else:
                topic = Topic.objects.select_related("language").get(slug=str(topic_ref))
        except Topic.DoesNotExist:
            return Response({"detail": "Topic not found."}, status=404)

        try:
            lang = topic.language
            if lang_abbr and lang_abbr.lower() != lang.abbreviation.lower():
                # nếu truyền abbr khác → ưu tiên abbr
                from .models import Language
                lang = Language.objects.get(abbreviation__iexact=lang_abbr)

            enrollment, _ = LanguageEnrollment.objects.get_or_create(
                user=request.user, language=lang,
                defaults={"total_xp": 0, "streak_days": 0}
            )
        except Exception:
            return Response({"detail": "Cannot resolve enrollment."}, status=400)

        # Get/create progress
        tp, _ = TopicProgress.objects.get_or_create(enrollment=enrollment, topic=topic)

        unlock_order = (tp.highest_completed_order or 0) + 1
        total_lessons = Lesson.objects.filter(topic=topic).count()

        ser = self.get_serializer(tp)
        data = ser.data
        data.update({
            "unlock_order": unlock_order,    
            "total_lessons": total_lessons,
        })
        return Response(data)


class RoleplayScenarioViewSet(viewsets.ModelViewSet):
    queryset = RoleplayScenario.objects.all().order_by("order","created_at")
    permission_classes = [IsAdminOrSuperAdmin]

    def get_serializer_class(self):
        if self.action in ["create", "update", "partial_update"]:
            return RoleplayScenarioWriteSerializer
        return RoleplayScenarioReadSerializer

    @action(detail=False, methods=["post"], url_path="bulk")
    @transaction.atomic
    def bulk_create(self, request):
        """
        STRICT (all-or-nothing):
        Chấp nhận:
          - JSON array: [ {scenario+blocks}, ... ]
          - hoặc wrapper: { "items": [ ... ] }
        """
        data = request.data
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict) and isinstance(data.get("items"), list):
            items = data["items"]
        else:
            return Response(
                {"detail": "Expected a JSON array or an object with 'items': [...]."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not items:
            return Response({"detail": "Empty payload."}, status=status.HTTP_400_BAD_REQUEST)

        ser = RoleplayScenarioWriteSerializer(data=items, many=True)
        ser.is_valid(raise_exception=True)      
        instances = ser.save()                      # DRF sẽ gọi child.create() từng phần tử
        read = RoleplayScenarioReadSerializer(instances, many=True).data
        return Response({"created": [it["slug"] for it in read], "items": read}, status=status.HTTP_201_CREATED)


class RoleplayBlockViewSet(viewsets.ModelViewSet):
    queryset = RoleplayBlock.objects.select_related("scenario").all()
    permission_classes = [IsAdminOrSuperAdmin]

    def get_serializer_class(self):
        if self.action in ["create", "update", "partial_update"]:
            return RoleplayBlockWriteSerializer
        return RoleplayBlockReadSerializer

    @action(detail=False, methods=["post"], url_path="embed", permission_classes=[IsAdminOrSuperAdmin])
    def embed_all(self, request):
        n = embed_blocks(force=bool(request.data.get("force")))
        return Response({"embedded": n})

    @action(detail=False, methods=["post"], url_path="search_text", permission_classes=[permissions.AllowAny])
    def search_text(self, request):
        q = (request.data.get("q_text") or "").strip()
        if not q: return Response({"detail":"q_text required"}, status=400)
        sc = request.data.get("scenario"); k = int(request.data.get("top_k") or 8)
        blocks = retrieve_blocks(q_text=q, top_k=k, scenario_slug=sc)
        return Response({"items": RoleplayBlockReadSerializer(blocks, many=True).data})

    
    @action(detail=False, methods=["post"], url_path="ask_gemini", permission_classes=[permissions.AllowAny])
    def ask(self, request):
        q = (request.data.get("query") or "").strip()
        if not q: return Response({"detail":"query required"}, status=400)
        sc = request.data.get("scenario"); k = int(request.data.get("top_k") or 8)
        blocks = retrieve_blocks(q_text=q, top_k=k, scenario_slug=sc)
        return Response({
          "answer": ask_gemini(q, blocks),
          "context": RoleplayBlockReadSerializer(blocks, many=True).data
        })


class RoleplaySessionViewSet(viewsets.ViewSet):
    permission_classes = [permissions.AllowAny]

    @action(detail=False, methods=["post"], url_path="start")
    def start(self, request):
        """
        body: { "scenario": "<slug|uuid>", "role": "student_b" }
        """
        sc = request.data.get("scenario")
        role = (request.data.get("role") or "").strip()
        if not sc or not role:
            return Response({"detail": "scenario and role required"}, status=400)

        scn = RoleplayScenario.objects.filter(slug=sc).first() \
              or get_object_or_404(RoleplayScenario, id=sc)

        blocks = ordered_blocks(scn)                           
        prologue, dialogue = split_prologue_and_dialogue(blocks)  # chỉ dialogue là lượt tương tác

        idx = 0
        ai_batch = []
        while idx < len(dialogue) and (dialogue[idx].role != role):
            ai_batch.append(dialogue[idx])
            idx += 1

        # Tạo session: idx trỏ VÀO block đầu tiên của người học (nếu có)
        sid = create_session(str(scn.id), role, [str(b.id) for b in dialogue])
        sess = get_session(sid)
        sess["idx"] = idx
        save_session(sid, sess)

        # await_user: kèm expected_text để FE gửi sang /speech/pron/up/
        await_user = None
        if idx < len(dialogue):
            nxt = dialogue[idx]
            await_user = {
                "block_id": str(nxt.id),      # luôn là lượt của người học
                "role": role,
                "order": nxt.order,
                "expected_text": nxt.text,    # <-- đáp án chuẩn
                "expected_hint": make_hint(nxt.text, 80),  # tuỳ chọn
            }

        return Response({
            "session_id": sid,
            "prologue": [
                {"role": b.role or "-", "text": b.text, "section": b.section, "order": b.order}
                for b in prologue
            ],
            "ai_utterances": ai_lines_for(ai_batch, learner_role=role),
            "await_user": await_user,
        })

    @action(detail=False, methods=["post"], url_path="submit")
    def submit(self, request):
        """
        body: {
        "session_id": "...",
        "transcript": "...",
        "pron": { ... }   # TÙY CHỌN — chỉ để FE hiển thị (score_overall, words, details,…)
        }
        """
        sid = request.data.get("session_id")
        transcript = (request.data.get("transcript") or "").strip()
        pron = request.data.get("pron") or {}
        sess = get_session(sid)
        if not (sid and sess and transcript):
            return Response({"detail":"session_id and transcript required/valid"}, status=400)

        dlg_ids = sess["dialogue_ids"]
        idx = int(sess.get("idx", 0))
        learner_role = sess["role"]

        # nhảy tới lượt user (phòng dữ liệu đổi)
        while idx < len(dlg_ids):
            blk = get_object_or_404(RoleplayBlock, id=dlg_ids[idx])
            if blk.role == learner_role:
                break
            idx += 1
        if idx >= len(dlg_ids):
            return Response({"status":"finished", "message":"Scenario done.", "next_ai":[]})

        blk = get_object_or_404(RoleplayBlock, id=dlg_ids[idx])

        # ---> Gate bằng cosine/lexical
        result = score_user_turn(blk.text, blk.embedding, transcript)
        if not result["passed"]:
            return Response({
                "passed": False,
                "score": result,          
                "pron": pron,           
                "feedback": "Gần đúng rồi. Luyện rõ hơn từ bị sai và giữ đủ ý chính nhé.",
                "expected_example": blk.text
            })

        # tiến hội thoại
        idx += 1
        ai_batch = []
        while idx < len(dlg_ids):
            nb = get_object_or_404(RoleplayBlock, id=dlg_ids[idx])
            if nb.role == learner_role:
                break
            ai_batch.append(nb)
            idx += 1

        sess["idx"] = idx
        save_session(sid, sess)

        next_await = None
        if idx < len(dlg_ids):
            nb = get_object_or_404(RoleplayBlock, id=dlg_ids[idx])
            next_await = {
                "block_id": str(nb.id),
                "role": learner_role,
                "order": nb.order,
                "expected_text": nb.text,
                "expected_hint": make_hint(nb.text, 80),
            }

        return Response({
            "passed": True,
            "score": result,                 # để FE show cos/lex
            "pron": pron,                    # chỉ feedback phát âm
            "next_ai": ai_lines_for(ai_batch, learner_role=learner_role),
            "await_user": next_await,
            "finished": idx >= len(dlg_ids),
        })