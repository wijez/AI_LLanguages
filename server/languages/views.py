from django.conf import time
from django.db import transaction
from rest_framework import viewsets, mixins, status, permissions
from drf_spectacular.utils import (
    extend_schema, OpenApiExample, OpenApiResponse
)
from drf_spectacular.types import OpenApiTypes
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from django.db.models import F, Max, Prefetch, Count
from django.utils.text import slugify
from django.utils.dateparse import parse_datetime
from django.shortcuts import get_object_or_404


from users.views import *
from speech.services_block_tts import generate_block_tts, generate_tts_from_text
from utils.permissions import HasInternalApiKey, IsAdminOrSuperAdmin
from rest_framework.permissions import AllowAny, IsAuthenticated

from languages.models import *
from languages.serializers import *
from rest_framework.viewsets import ReadOnlyModelViewSet
from vocabulary.models import Mistake, LearningInteraction
from learning.models import LessonSession
from languages.services.embed_pipeline import embed_blocks
from languages.services.rag import ask_gemini_chat, retrieve_blocks, ask_gemini
from languages.services.roleplay_flow import ordered_blocks, split_prologue_and_dialogue, practice_blocks
from languages.services.ai_speaker import ai_lines_for
from languages.services.session_mem import create_session, get_session, save_session
from languages.services.validate_turn import score_user_turn, make_hint
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend


class LanguageViewSet(viewsets.ModelViewSet):
    queryset = Language.objects.all()
    serializer_class = LanguageSerializer
    filter_backends = [SearchFilter]
    search_fields = ['name', 'abbreviation', 'native_name']

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
            qs = qs.filter(language__abbreviation__iexact=abbr)
        
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


    """
    gán skill vào 1 lesson
    {
        "skill_id": 123,
        "order": 2
    }
    """
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
                skill_id = raw.pop("skill_id", None)
                if skill_id:
                    skill = get_object_or_404(Skill, pk=skill_id)
                else:
                    # 2) Không có skill_id -> tạo mới skill
                    ser = SkillSerializer(
                        data=raw,
                        context=self.get_serializer_context()
                    )
                    ser.is_valid(raise_exception=True)
                    skill = ser.save()

                # Tạo bản ghi nối và set order
                if order is None:
                    current += 1
                    order_local = current
                else:
                    order_local = order
                LessonSkill.objects.create(lesson=lesson, skill=skill, order=order_local)
                if not created and order is not None and ls.order != order_local:
                    ls.order = order_local
                    ls.save(update_fields=["order"])
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
    @action(detail=True, methods=["post"], url_path="attach-skill",
            permission_classes=[permissions.IsAuthenticated])
    @transaction.atomic
    def attach_skill(self, request, pk=None):
        """
        GẮN skill đã tồn tại vào lesson.
        Body:
          - 1 skill: { "skill": 54, "order": 3? }
          - nhiều skill:
            [
              { "skill": 54, "order": 3 },
              { "skill": 58 },  # auto append cuối
            ]
        """
        lesson = self.get_object()
        many = isinstance(request.data, list)
        items = request.data if many else [request.data]

        out = []
        # order hiện tại lớn nhất trong lesson
        current = LessonSkill.objects.filter(lesson=lesson).aggregate(
            m=Max("order")
        )["m"] or 0

        for raw in items:
            skill_id = raw.get("skill") or raw.get("skill_id")
            if not skill_id:
                raise serializers.ValidationError(
                    {"skill": "This field is required."}
                )

            try:
                skill = Skill.objects.get(pk=skill_id)
            except Skill.DoesNotExist:
                raise serializers.ValidationError(
                    {"skill": f"Skill {skill_id} not found."}
                )

            order = raw.get("order")
            if order is None:
                current += 1
                order = current

            # unique_together(lesson, skill) → dùng get_or_create
            ls, created = LessonSkill.objects.get_or_create(
                lesson=lesson,
                skill=skill,
                defaults={"order": order},
            )
            if not created and ls.order != order:
                ls.order = order
                ls.save(update_fields=["order"])

            out.append(
                {
                    "lesson": lesson.id,
                    "skill": skill.id,
                    "order": ls.order,
                    "created": created,
                }
            )

        return Response(out if many else out[0], status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="reorder-skills",
            permission_classes=[permissions.IsAuthenticated])
    @transaction.atomic
    def reorder_skills(self, request, pk=None):
        """
        CẬP NHẬT order của các skill trong 1 lesson.
        Body:
          {
            "items": [
              { "skill": 54, "order": 1 },
              { "skill": 58, "order": 2 },
              ...
            ]
          }
        """
        lesson = self.get_object()
        items = request.data.get("items") or []
        if not isinstance(items, list):
            raise serializers.ValidationError(
                {"items": "Must be a list of {skill, order}."}
            )

        for item in items:
            skill_id = item.get("skill") or item.get("skill_id")
            order = item.get("order")
            if skill_id is None or order is None:
                continue
            LessonSkill.objects.filter(
                lesson=lesson, skill_id=skill_id
            ).update(order=order)

        return Response({"detail": "ok"}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="remove-skill",
            permission_classes=[permissions.IsAuthenticated])
    @transaction.atomic
    def remove_skill(self, request, pk=None):
        """
        GỠ skill khỏi lesson (không xóa Skill).
        Body:
          { "skill": 54 }
        """
        lesson = self.get_object()
        skill_id = request.data.get("skill") or request.data.get("skill_id")
        if not skill_id:
            raise serializers.ValidationError(
                {"skill": "This field is required."}
            )

        deleted, _ = LessonSkill.objects.filter(
            lesson=lesson, skill_id=skill_id
        ).delete()
        return Response(
            {
                "detail": "removed" if deleted else "not_found",
                "deleted": deleted,
            },
            status=status.HTTP_200_OK,
        )


class TopicViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminOrSuperAdmin]
    queryset = Topic.objects.select_related("language").all()
    serializer_class = TopicSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    
    search_fields = ['title', 'slug', 'description']  
    filterset_fields = ['language', 'golden', 'id']  
    ordering_fields = ['order', 'created_at', 'title']
    ordering = ['order', 'id']

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
  
    @action(detail=True, methods=['get', 'post'], url_path='lessons')
    def lessons(self, request, pk=None):
        """
        GET: Lấy danh sách lesson (kèm progress/skills)
        POST: Tạo lesson mới
        """
        if request.method == 'POST':
            topic = self.get_object()
            serializer = LessonCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(topic=topic)
            
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        include_skills = str(request.query_params.get("include_skills", "0")).lower() in ("1","true","yes")
        include_progress = str(request.query_params.get("include_progress", "0")).lower() in ("1","true","yes")

        qs = (Lesson.objects
            .filter(topic_id=pk)
            .order_by("order", "id"))

        if include_skills:
            qs = qs.prefetch_related(
                Prefetch("skills", queryset=Skill.objects.filter(is_active=True).order_by("lessonskill__order", "id"))
            )

        if include_skills:
            base = LessonWithSkillsSerializer(qs, many=True, context=self.get_serializer_context()).data
        else:
            base = LessonLiteSerializer(qs, many=True, context=self.get_serializer_context()).data

        data = list(base)

        if include_progress and request.user.is_authenticated:
            try:
                topic = Topic.objects.select_related("language").get(pk=pk)
                enrollment = LanguageEnrollment.objects.filter(user_id=request.user.id, language=topic.language).first()

                if enrollment:
                    qs_prog = qs.annotate(
                        total_skills=Count("skills", filter=Q(skills__is_active=True), distinct=True),
                        done_skills=Count("skills", filter=Q(skills__userskillstats__enrollment_id=enrollment.id, skills__userskillstats__status__in=["completed", "mastered"]), distinct=True),
                    )
                    meta = {row.id: {"total": row.total_skills or 0, "done": row.done_skills or 0, "order": row.order} for row in qs_prog}
                    
                    tp = TopicProgress.objects.filter(enrollment=enrollment, topic_id=pk).first()
                    unlock_order = (tp.highest_completed_order if tp else 0) + 1
                    
                    for item in data:
                        m = meta.get(item["id"], {"total": 0, "done": 0, "order": 0})
                        pct = int(round(m["done"] * 100 / m["total"])) if m["total"] else 0
                        item["progress"] = {"total": m["total"], "done": m["done"], "percent": pct}
                        item["locked"] = not ((item.get("order") or m["order"] or 0) <= unlock_order)
            except Exception:
                pass

        return Response(data)


class SkillViewSet(mixins.ListModelMixin,
                   mixins.CreateModelMixin,
                   mixins.UpdateModelMixin,
                   mixins.DestroyModelMixin,
                   mixins.RetrieveModelMixin,
                   viewsets.GenericViewSet):
    
    serializer_class = SkillSerializer

    def get_permissions(self):
        open_actions = {"list", "retrieve", "questions", "children"}
        if getattr(self, "action", None) in open_actions or self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [AllowAny()]
        return [IsAdminOrSuperAdmin()]
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

    # def get_queryset(self):
    #     qs = self._base_queryset()

    #     # ?topic= (id hoặc slug) qua M2M LessonSkill: lessons__topic__
    #     t = self.request.query_params.get("topic")
    #     if t:
    #         if t.isdigit():
    #             qs = qs.filter(lessons__topic_id=int(t))
    #         else:
    #             qs = qs.filter(lessons__topic__slug=t)
    #         qs = qs.distinct()

    #     # ?type=
    #     ty = self.request.query_params.get("type")
    #     if ty:
    #         qs = qs.filter(type=ty)

    #     # lọc theo lesson_id + sắp xếp theo LessonSkill.order
    #     lesson = self.request.query_params.get("lesson")
    #     if lesson:
    #         qs = qs.filter(lessonskill__lesson_id=lesson) \
    #             .annotate(ls_order=F("lessonskill__order")) \
    #             .order_by("ls_order", "id")

    #     return qs
    def get_queryset(self):
        qs = self._base_queryset()

        # ?topic=... (giữ nguyên)
        t = self.request.query_params.get("topic")
        if t:
            if t.isdigit():
                qs = qs.filter(lessons__topic_id=int(t))
            else:
                qs = qs.filter(lessons__topic__slug=t)
            qs = qs.distinct()

        # ?type=pron
        ty = self.request.query_params.get("type")
        if ty:
            qs = qs.filter(type=ty)

        #  ?language=en | ?language_code=en | ?lang=en | ?code=en
        lang = (self.request.query_params.get("language")
                or self.request.query_params.get("language_code")
                or self.request.query_params.get("lang")
                or self.request.query_params.get("code"))
        if lang:
            qs = qs.filter(language_code__iexact=lang)

        # ?lesson=... 
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

            # Gắn vào LessonSkill  lesson_id
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

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]

    search_fields = ["title", "slug", "description"]

    ordering_fields = ["order", "created_at", "updated_at", "level", "title"]
    ordering = ["order", "created_at"] 

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

    def perform_create(self, serializer):
        block = serializer.save()
        self._ensure_tts(block)
        try:
            embed_blocks([block], force=True)
        except Exception as e:
            print(f"[EMBED ERROR] Could not embed block {block.id}: {e}")

    def perform_update(self, serializer):
        block = serializer.save()
        self._ensure_tts(block)
        if "text" in self.request.data:
            try:
                embed_blocks([block], force=True)
            except Exception as e:
                print(f"[EMBED ERROR] Could not re-embed block {block.id}: {e}")

    def _ensure_tts(self, block):
        """
        Tạo hoặc cập nhật audio_key nếu cần
        """
        try:
            # chỉ tạo nếu chưa có hoặc text thay đổi
            if not block.audio_key or "text" in self.request.data:
                audio_url = generate_block_tts(block)
                if audio_url:
                    block.audio_key = audio_url
                    block.save(update_fields=["audio_key"])
        except Exception as e:
            # không block việc save block
            print("[TTS BLOCK ERROR]", e)


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
        if not q: 
            return Response({"detail":"query required"}, status=400)
        if len(q) > 1000: 
            return Response({"detail":"Query is too long."}, status=status.HTTP_400_BAD_REQUEST)
        sc = request.data.get("scenario")
        k = int(request.data.get("top_k") or 8)
        if k > 20: 
            k = 20
        blocks = retrieve_blocks(q_text=q, top_k=k, scenario_slug=sc)

        answer = ask_gemini(q, blocks)
        return Response({
          "answer":  answer,
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
                {"role": b.role or "-", "text": b.text, "section": b.section,"audio_key": b.audio_key, "order": b.order}
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
                "audio_key": nb.audio_key,
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

    @action(detail=False, methods=["post"], url_path="start-practice")
    def start_practice(self, request):
        serializer = PracticeStartIn(data=request.data)
        serializer.is_valid(raise_exception=True)

        sc_slug = serializer.validated_data["scenario"]
        role = serializer.validated_data["role"]
        language = serializer.validated_data.get("language", "vi")

        scn = (
            RoleplayScenario.objects.filter(slug=sc_slug).first()
            or get_object_or_404(RoleplayScenario, id=sc_slug)
        )

        # 1. Load blocks
        all_blocks = RoleplayBlock.objects.filter(
            scenario=scn
        ).order_by("order")

        context_blocks = []
        warmup_blocks = []

        for b in all_blocks:
            if b.section == "warmup":
                warmup_blocks.append(b)
            else:
                context_blocks.append(b)

        # 2. Build SYSTEM CONTEXT
        sys_ctx = f"""
            Scenario: {scn.title}
            Level: {scn.level}
            Learner support language: {language}

            You are an AI language tutor participating in a roleplay conversation for language learning.

            Your task is NOT to translate blindly.
            You MUST follow the 4-step response structure below whenever the USER speaks English.

            The TARGET_LANGUAGE is: {language}

            === REQUIRED PROCESSING RULES ===

            1. USER ORIGINAL
            - Preserve the user's original English sentence exactly as written.
            - Do NOT modify it.

            2. GRAMMAR & STRUCTURE FIX
            - Provide a corrected English version.
            - Fix grammar, word choice, structure.
            - Preserve meaning.
            - If already correct, repeat unchanged.

            3. MEANING (TARGET_LANGUAGE)
            - Translate ONLY the corrected sentence.
            - Use natural {language}.

            4. AI RESPONSE (ROLEPLAY CONTINUATION)
            - Continue the roleplay naturally in English.
            - Ask at least ONE follow-up question.
            - Then translate your response to {language}.

            === OUTPUT FORMAT (STRICT) ===

            USER (Original):
            {{user_sentence}}

            AI – Grammar Fix:
            {{corrected_sentence}}

            AI – Meaning ({language}):
            {{translated_meaning}}

            AI – Response (EN):
            {{ai_reply}}

            AI – Response ({language}):
            {{translated_reply}}

            === SECTION AWARENESS ===
            """

        for b in context_blocks:
            sys_ctx += f"\n[{b.section.upper()}]: {b.text}\n"

        sys_ctx += f"""
            ROLE DEFINITION
            - The user plays the role: {role}
            - You play all other necessary roles.

            CORE BEHAVIOR
            - You are the ACTIVE conversation driver.
            - NEVER end a turn without a question.
            - Stay strictly within scenario and instruction blocks.

            FORBIDDEN
            - NEVER skip steps
            - NEVER merge steps
            - NEVER answer without a question
            """

        # 3. Init history
        history = []
        ai_greeting_data = None

        if warmup_blocks:
            first_warmup = warmup_blocks[0]
            history.append({
                "role": "model",
                "parts": [first_warmup.text]
            })
            ai_greeting_data = {
                "text": first_warmup.text,
                "audio_key": first_warmup.audio_key,
                "role": "assistant"
            }

        # 4. Create session
        sid = str(uuid.uuid4())

        if request.user.is_authenticated:
            PracticeSession.objects.create(
                id=sid,
                user=request.user,
                scenario=scn,
                role=role,
                system_context=sys_ctx,
                history_log=history
            )

        save_session(sid, {
            "mode": "practice",
            "scenario_id": str(scn.id),
            "user_role": role,
            "system_context": sys_ctx,
            "history": history,
            "created_at": int(time.time()),
            "language": language,
        })

        return Response({
            "session_id": sid,
            "prologue": [RoleplayBlockReadSerializer(b).data for b in context_blocks],
            "ai_greeting": ai_greeting_data,
            "message": "Session started"
        })


    @action(detail=False, methods=["post"], url_path="submit-practice")
    def submit_practice(self, request):
        serializer = PracticeSubmitIn(data=request.data)
        serializer.is_valid(raise_exception=True)
        sid = serializer.validated_data["session_id"]
        transcript = serializer.validated_data["transcript"]

        # A. Ưu tiên lấy từ Cache
        sess = get_session(sid)
        
        # B Nếu Cache mất (do restart server), thử phục hồi từ DB
        if not sess:
            try:
                db_sess = PracticeSession.objects.get(id=sid)
                # Rehydrate cache từ DB
                sess = {
                    "mode": "practice",
                    "scenario_id": str(db_sess.scenario.id),
                    "user_role": db_sess.role,
                    "system_context": db_sess.system_context,
                    "history": db_sess.history_log,
                    "created_at": db_sess.created_at.timestamp()
                }
                save_session(sid, sess) # Lưu lại vào cache
            except PracticeSession.DoesNotExist:
                return Response({"detail": "Invalid session"}, status=400)

        if sess.get("mode") != "practice":
             return Response({"detail": "Session mode mismatch"}, status=400)

        history = sess.get("history", [])
        sys_ctx = sess.get("system_context", "")
        
        # 1. Gọi Gemini
        ai_data = ask_gemini_chat(sys_ctx, history, transcript)
        
        ai_reply = ai_data.get("reply", "") or "..."
        correction = ai_data.get("corrected")
        explanation = ai_data.get("explanation")

        # 2. Update History
        history.append({"role": "user", "parts": [transcript]})
        history.append({"role": "model", "parts": [ai_reply]})
        sess["history"] = history
        save_session(sid, sess)

        if request.user.is_authenticated:
            PracticeSession.objects.filter(id=sid).update(
                history_log=history,
                updated_at=timezone.now()
            )

        # 4. Sinh Audio
        ai_audio = generate_tts_from_text(ai_reply, lang="en")

        return Response({
            "user_transcript": transcript,
            "ai_text": ai_reply,
            "ai_audio": ai_audio,
            "feedback": {
                "has_error": bool(correction),
                "original": transcript,
                "corrected": correction,
                "explanation": explanation
            }
        })

    @action(detail=False, methods=["get"], url_path="history", permission_classes=[IsAuthenticated])
    def history(self, request):
        """
        Lấy danh sách các phiên Practice cũ.
        Yêu cầu GenericViewSet để có self.paginate_queryset.
        """
        qs = PracticeSession.objects.filter(user=request.user).select_related('scenario')
        
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = PracticeSessionSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = PracticeSessionSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="resume", permission_classes=[IsAuthenticated])
    def resume(self, request, pk=None):
        """
        Lấy chi tiết và nạp lại Cache cho một phiên cũ
        """
        session = get_object_or_404(PracticeSession, pk=pk, user=request.user)
        
        # Nạp lại Cache để user chat tiếp 
        sid = str(session.id)
        sess_data = {
            "mode": "practice",
            "scenario_id": str(session.scenario.id),
            "user_role": session.role,
            "system_context": session.system_context,
            "history": session.history_log,
            "created_at": session.created_at.timestamp()
        }
        save_session(sid, sess_data)

        return Response(PracticeSessionDetailSerializer(session).data)


class PracticeSessionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API quản lý lịch sử Practice Session.
    - GET /api/practice-sessions/     : Danh sách rút gọn
    - GET /api/practice-sessions/{id}/: Chi tiết đầy đủ (kèm history_log)
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return PracticeSession.objects.filter(user=self.request.user).select_related('scenario').order_by('-updated_at')

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return PracticeSessionDetailSerializer
        return PracticeSessionSerializer