from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets, permissions, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from django.db.models import F, Prefetch

from languages.models import (
    Lesson, Skill, LanguageEnrollment, UserSkillStats,
    SkillQuestion, SkillChoice, ListeningPrompt, PronunciationPrompt,
    ReadingContent, ReadingQuestion, WritingQuestion, SkillGap,
    MatchingPair, OrderingItem, SpeakingPrompt
)
from .models import LessonSession, SessionAnswer
from vocabulary.models import Mistake, LearningInteraction

from languages.serializers import SkillSerializer
from .serializers import (
    LessonSessionOut, StartSessionIn, AnswerIn, CompleteSessionIn, CancelSessionIn
)
import re
import unicodedata


# ============ Utils for checking ============
def _lesson_skills_qs(lesson_id: int):
    """
    Lấy Skill của 1 lesson theo đúng thứ tự LessonSkill.order,
    kèm prefetch đầy đủ các bảng con để serialize nested.
    """
    return (
        Skill.objects
        .filter(lessonskill__lesson_id=lesson_id, is_active=True)
        .select_related("reading_content")
        .prefetch_related(
            Prefetch("quiz_questions",
                     queryset=SkillQuestion.objects.prefetch_related("choices").order_by("id")),
            Prefetch("fillgaps", queryset=SkillGap.objects.order_by("id")),
            Prefetch("ordering_items", queryset=OrderingItem.objects.order_by("order_index", "id")),
            Prefetch("matching_pairs", queryset=MatchingPair.objects.order_by("id")),
            Prefetch("listening_prompts", queryset=ListeningPrompt.objects.order_by("id")),
            Prefetch("pronunciation_prompts", queryset=PronunciationPrompt.objects.order_by("id")),
            Prefetch("reading_questions", queryset=ReadingQuestion.objects.order_by("id")),
            Prefetch("writing_questions", queryset=WritingQuestion.objects.order_by("id")),
            Prefetch("speaking_prompts", queryset=SpeakingPrompt.objects.order_by("id")),
        )
        .annotate(ls_order=F("lessonskill__order"))
        .order_by("ls_order", "id")
    )

def _canon(text: str, strip_accents=True, strip_punct=True) -> str:
    """Chuẩn hoá để so khớp: lower, (tuỳ) bỏ dấu, (tuỳ) bỏ punctuation, gộp khoảng trắng."""
    s = str(text or "").strip().lower()
    if strip_accents:
        s = unicodedata.normalize("NFKD", s)
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
    if strip_punct:
        s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _canon_for_type(text: str, skill_type: str) -> str:
    """
    Nới lỏng cho quiz/listening/matching/pron; giữ chặt cho reading/writing/fillgap.
    ordering xử lý riêng (join token rồi canon).
    """
    tight = {"reading", "writing", "fillgap"}
    if skill_type in tight:
        # chỉ lower/trim (KHÔNG bỏ dấu/punctuation)
        return _canon(text, strip_accents=False, strip_punct=False)
    # mặc định nới lỏng
    return _canon(text, strip_accents=True, strip_punct=True)

def _parse_int(val):
    try:
        return int(val)
    except Exception:
        return None


# ============ Resolver for expected/prompt theo schema mới ============
def _get_expected_and_prompt(skill: Skill, question_id: str):
    """
    Trả về (expected, prompt, skill_type) theo schema mới (tách bảng con).
    - quiz:           SkillQuestion(id)  → expected = text của choice is_correct=True; prompt = question_text
    - listening:      ListeningPrompt(id)→ expected = answer; prompt = question_text (+audio trong ngoặc nếu muốn)
    - reading:        ReadingQuestion(id)→ expected = answer; prompt = passage + 2 dòng trống + question_text
    - writing:        WritingQuestion(id)→ expected = answer; prompt = prompt
    - fillgap:        SkillGap(id)       → expected = answer; prompt = text
    - matching:       MatchingPair(id)   → expected = right_text; prompt = f"Chọn nghĩa đúng: {left_text}"
    - pron:           PronunciationPrompt(id) → expected = answer or word; prompt = f"Phát âm: word (phonemes)"
    - speaking:       SpeakingPrompt(id) → expected = target; prompt = f"Nói lại: text (tip)"
    - ordering:       không dùng question_id; expected = list token theo order_index; prompt cố định
    """
    t = getattr(skill, "type", "")

    if t == "quiz":
        qid = _parse_int(question_id)
        q = SkillQuestion.objects.prefetch_related("choices").get(pk=qid, skill=skill)
        correct = next((c for c in q.choices.all() if c.is_correct), None)
        expected = correct.text if correct else ""
        prompt = q.question_text or ""
        return expected, prompt, t

    if t == "listening":
        qid = _parse_int(question_id)
        p = ListeningPrompt.objects.get(pk=qid, skill=skill)
        prompt = p.question_text or ""
        if p.audio_url:
            prompt = f"{prompt} [audio: {p.audio_url}]".strip()
        return p.answer or "", prompt, t

    if t == "reading":
        qid = _parse_int(question_id)
        q = ReadingQuestion.objects.select_related("skill__reading_content").get(pk=qid, skill=skill)
        passage = getattr(getattr(skill, "reading_content", None), "passage", "") or ""
        prompt = f"{passage}\n\n{q.question_text}".strip() if passage else (q.question_text or "")
        return q.answer or "", prompt, t

    if t == "writing":
        qid = _parse_int(question_id)
        q = WritingQuestion.objects.get(pk=qid, skill=skill)
        return (q.answer or ""), (q.prompt or ""), t

    if t == "fillgap":
        qid = _parse_int(question_id)
        g = SkillGap.objects.get(pk=qid, skill=skill)
        return (g.answer or ""), (g.text or ""), t

    if t == "matching":
        qid = _parse_int(question_id)
        m = MatchingPair.objects.get(pk=qid, skill=skill)
        prompt = f"Chọn nghĩa đúng: {m.left_text}"
        return (m.right_text or ""), prompt, t

    if t == "pron":
        qid = _parse_int(question_id)
        p = PronunciationPrompt.objects.get(pk=qid, skill=skill)
        phon = f" ({p.phonemes})" if getattr(p, "phonemes", "") else ""
        prompt = f"Phát âm: {p.word}{phon}"
        expected = getattr(p, "answer", "") or (p.word or "")
        return expected, prompt, t

    if t == "speaking":
        qid = _parse_int(question_id)
        s = SpeakingPrompt.objects.get(pk=qid, skill=skill)
        tip = f" — {s.tip}" if s.tip else ""
        prompt = f"Nói lại: {s.text}{tip}"
        return (s.target or ""), prompt, t

    if t == "ordering":
        items = list(OrderingItem.objects.filter(skill=skill).order_by("order_index", "id"))
        expected = [it.text for it in items]  # giữ dạng list để so khớp chuẩn
        prompt = "Sắp xếp các từ thành câu đúng"
        return expected, prompt, t

    # fallback
    return "", "", t


def _compare_answer(expected, user_answer: str, skill_type: str) -> bool:
    """So khớp theo loại đáp án."""
    if expected is None:
        return False

    # ordering: expected là list token
    if skill_type == "ordering" and isinstance(expected, (list, tuple)):
        exp_text = " ".join(map(str, expected))
        return _canon(exp_text) == _canon(user_answer)

    # danh sách đáp án hợp lệ (nhiều đáp án đúng)
    if isinstance(expected, (list, tuple)):
        exp_norms = {_canon_for_type(x, skill_type) for x in expected}
        return _canon_for_type(user_answer, skill_type) in exp_norms

    # đơn đáp án
    return _canon_for_type(expected, skill_type) == _canon_for_type(user_answer, skill_type)


def _map_source_from_skill(skill: Skill) -> str:
    m = {
        "pron": "pronunciation",
        "listening": "listening",
        "matching": "vocab",
        "quiz": "grammar",
        "reading": "grammar",
        "writing": "grammar",
        "fillgap": "grammar",
        "ordering": "grammar",
    }
    return m.get(getattr(skill, "type", ""), "other")


# ============ ViewSet ============
class LessonSessionViewSet(mixins.RetrieveModelMixin,
                           mixins.ListModelMixin,
                           viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = LessonSession.objects.all()
    serializer_class = LessonSessionOut

    def get_queryset(self):
        return super().get_queryset().filter(user=self.request.user)

    def retrieve(self, request, *args, **kwargs):
        session = self.get_object()
        data = LessonSessionOut(session).data
        skills_qs = _lesson_skills_qs(session.lesson_id)
        data["skills"] = SkillSerializer(skills_qs, many=True).data
        return Response(data)

    @action(detail=False, methods=["post"], url_path="start")
    @transaction.atomic
    def start(self, request):
        s = StartSessionIn(data=request.data)
        s.is_valid(raise_exception=True)
        lesson: Lesson = s.validated_data["lesson"]
        enrollment: LanguageEnrollment = s.validated_data["enrollment"]

        # safety checks
        if enrollment.user_id != request.user.id:
            return Response({"detail": "Enrollment không thuộc user."}, status=403)
        if enrollment.language_id != lesson.topic.language_id:
            return Response({"detail": "Enrollment và Lesson không cùng ngôn ngữ."}, status=400)

        session = LessonSession.objects.create(
            user=request.user, lesson=lesson, enrollment=enrollment, status="in_progress"
        )

        # log start
        LearningInteraction.objects.create(
            user=request.user, enrollment=enrollment, lesson=lesson,
            action="start_lesson", success=True, duration_seconds=0, xp_earned=0, meta={}
        )

        # trả kèm skills nested (đúng thứ tự)
        skills_qs = _lesson_skills_qs(lesson.id)
        skills_data = SkillSerializer(skills_qs, many=True).data

        data = LessonSessionOut(session).data
        data["skills"] = skills_data
        return Response(data, status=201)


    @action(detail=True, methods=["post"], url_path="answer")
    @transaction.atomic
    def answer(self, request, pk=None):
        session: LessonSession = self.get_object()
        if session.status != "in_progress":
            return Response({"detail": "Session không còn ở trạng thái in_progress."}, status=400)

        ser = AnswerIn(data=request.data)
        ser.is_valid(raise_exception=True)
        v = ser.validated_data

        skill: Skill = v["skill"]
        # skill phải thuộc lesson của session (qua bảng LessonSkill)
        belongs = Skill.objects.filter(
            lessonskill__lesson_id=session.lesson_id,
            pk=skill.pk
        ).exists()
        if not belongs:
            return Response({"detail": "Skill không thuộc lesson của session."}, status=400)

        # --- SERVER CHECK ---
        qid = v["question_id"]
        user_answer = v.get("user_answer", "")
        expected, prompt_text, skill_type = _get_expected_and_prompt(skill, qid)
        ok = _compare_answer(expected, user_answer, skill_type)
        # ---------------------

        # Lưu câu trả lời vào SessionAnswer (KHÔNG có trường 'score' theo yêu cầu)
        SessionAnswer.objects.create(
            session=session,
            skill=skill,
            question_id=qid,
            is_correct=ok,
            user_answer=user_answer,
            expected=(" ".join(expected) if (skill_type == "ordering" and isinstance(expected, (list, tuple))) else (expected or "")),
            meta={
                "client": "web",
                **({"dur": v["duration_seconds"]} if v.get("duration_seconds") else {})
            }
        )

        # cập nhật counters & XP
        session.total_questions += 1
        xp_gain = 0
        if ok:
            session.correct_answers += 1
            xp_gain = v.get("xp_on_correct", 5)
            session.xp_earned += xp_gain
        else:
            session.incorrect_answers += 1

        # append event
        now = timezone.now()
        ad = session.answers_data or {}
        events = ad.get("events", [])
        events.append({
            "t": now.isoformat(),
            "skill_id": skill.id,
            "q": qid,
            "ok": ok,
        })
        ad["events"] = events
        session.answers_data = ad
        session.last_activity = now
        session.save(update_fields=[
            "total_questions", "correct_answers", "incorrect_answers",
            "xp_earned", "answers_data", "last_activity"
        ])

        # log LearningInteraction
        li = LearningInteraction.objects.create(
            user=request.user,
            enrollment=session.enrollment,
            lesson=session.lesson,
            skill=skill,
            action="practice_skill",
            value=(1.0 if ok else 0.0),
            success=ok,
            duration_seconds=v.get("duration_seconds") or 0,
            xp_earned=xp_gain,
            meta={"question_id": qid}
        )

        # nếu sai → tạo Mistake gắn lesson + skill
        mistake_id = None
        if not ok:
            m = Mistake.objects.create(
                user=request.user,
                enrollment=session.enrollment,
                interaction=li,
                lesson=session.lesson,      # ⬅️ gắn lesson chứa skill sai
                skill=skill,                # ⬅️ gắn skill sai
                source=v.get("source") or _map_source_from_skill(skill),
                prompt=v.get("question") or (prompt_text or ""),
                expected=(" ".join(expected) if (skill_type == "ordering" and isinstance(expected, (list, tuple))) else (expected or "")),
                user_answer=user_answer,
                error_detail={"question_id": qid},
            )
            mistake_id = m.id

            # Đánh dấu skill cần ôn tập
            uss, _ = UserSkillStats.objects.get_or_create(
                enrollment=session.enrollment, skill=skill,
                defaults={"status": "available"}
            )
            uss.mark_for_review()

        # Trả expected để FE hiện đáp án đúng; kèm mistake_id nếu có
        resp = {
            "session": LessonSessionOut(session).data,
            "xp_gain": xp_gain,
            "server_checked": True,
            "correct": ok,
        }
        if expected is not None:
            resp["expected"] = (" ".join(expected) if (skill_type == "ordering" and isinstance(expected, (list, tuple))) else (expected or ""))

        if mistake_id:
            resp["mistake_id"] = mistake_id

        return Response(resp, status=200)

    @action(detail=True, methods=["post"], url_path="complete")
    @transaction.atomic
    def complete(self, request, pk=None):
        session: LessonSession = self.get_object()
        c = CompleteSessionIn(data=request.data)
        c.is_valid(raise_exception=True)

        # chốt XP: nếu client không ép, giữ xp_earned đã tích luỹ
        final_xp = c.validated_data.get("final_xp", session.xp_earned)

        # cập nhật UserSkillStats cho các skill đã luyện trong session
        # XP cho từng skill = số câu đúng của skill *  (final_xp / tổng câu đúng) (chia theo tỉ lệ)
        answers = list(session.answers.select_related("skill").all())
        by_skill = {}
        total_correct = 0
        for a in answers:
            if a.is_correct and a.skill_id:
                total_correct += 1
                by_skill[a.skill_id] = by_skill.get(a.skill_id, 0) + 1

        for skill_id, correct_cnt in by_skill.items():
            try:
                skill = next(a.skill for a in answers if a.skill_id == skill_id)
            except StopIteration:
                continue
            per_skill_xp = int(final_xp * (correct_cnt / max(1, total_correct)))
            uss, _ = UserSkillStats.objects.get_or_create(
                enrollment=session.enrollment, skill=skill,
                defaults={"status": "available"}
            )
            uss.complete_lesson(xp_earned=per_skill_xp)

        # complete session (tự cộng XP vào enrollment + perfect bonus)
        session.complete_session(final_xp=final_xp)

        # log complete_lesson
        LearningInteraction.objects.create(
            user=request.user, enrollment=session.enrollment, lesson=session.lesson,
            action="complete_lesson", success=True,
            duration_seconds=session.duration_seconds, xp_earned=session.xp_earned, meta={}
        )

        return Response(LessonSessionOut(session).data, status=200)

    @action(detail=True, methods=["post"], url_path="cancel")
    @transaction.atomic
    def cancel(self, request, pk=None):
        """
        Hủy phiên học:
        - Nếu as_failed = False (mặc định): status → 'abandoned'
        - Nếu as_failed = True: status → 'failed'
        - Không cộng XP vào enrollment (vì chưa complete).
        - Ghi LearningInteraction: abandon_lesson / fail_lesson (success=False)
        """
        session = self.get_object()
        if session.status != "in_progress":
            return Response(
                {"detail": "Chỉ có thể hủy khi session đang 'in_progress'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        ser = CancelSessionIn(data=request.data)
        ser.is_valid(raise_exception=True)
        v = ser.validated_data

        now = timezone.now()
        session.status = "failed" if v.get("as_failed") else "abandoned"
        session.completed_at = now
        if session.started_at:
            session.duration_seconds = int((now - session.started_at).total_seconds())
        session.last_activity = now
        session.save(update_fields=["status", "completed_at", "duration_seconds", "last_activity"])

        # Ghi interaction
        LearningInteraction.objects.create(
            user=request.user,
            enrollment=session.enrollment,
            lesson=session.lesson,
            action="fail_lesson" if v.get("as_failed") else "abandon_lesson",
            success=False,
            duration_seconds=session.duration_seconds or 0,
            xp_earned=0,
            meta={"reason": v.get("reason", "")},
        )

        return Response(LessonSessionOut(session).data, status=status.HTTP_200_OK)
