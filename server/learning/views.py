import os
from django.db import transaction
from django.forms import FloatField
from django.utils import timezone
from rest_framework import viewsets, permissions, mixins
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.conf import settings
from django.db.models import F, Avg, Case, Max, Prefetch, Count, Q, When
import requests

from languages.models import (
    Language, Lesson, RoleplayScenario, Skill, LanguageEnrollment, UserSkillStats,
    SkillQuestion, SkillChoice, ListeningPrompt, PronunciationPrompt,
    ReadingContent, ReadingQuestion, WritingQuestion, SkillGap,
    MatchingPair, OrderingItem, SpeakingPrompt, TopicProgress, PracticeSession
)
from vocabulary.models import Word, KnownWord
from progress.models import DailyXP
from .models import LessonSession, SessionAnswer, SkillSession, PronAttempt
from vocabulary.models import Mistake, LearningInteraction

from languages.serializers import SkillSerializer
from .serializers import *
import re
import unicodedata
from social.services import award_xp_from_lesson, recalc_badges_for_user
from languages.services.validate_turn import _seq_ratio

# ============ Utils for checking ============
def _lesson_skills_qs(lesson_id: int):
    return (
        Skill.objects
        .filter(lessonskill__lesson_id=lesson_id, is_active=True)
        .select_related("reading_content")
        .prefetch_related(
            Prefetch("quiz_questions", queryset=SkillQuestion.objects.prefetch_related("choices").order_by("id")),
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
    s = str(text or "").strip().lower()
    if strip_accents:
        s = unicodedata.normalize("NFKD", s)
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
    if strip_punct:
        s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _canon_for_type(text: str, skill_type: str) -> str:
    tight = {"reading", "writing", "fillgap"}
    if skill_type in tight:
        return _canon(text, strip_accents=False, strip_punct=False)
    return _canon(text, strip_accents=True, strip_punct=True)

def _parse_int(val):
    try:
        return int(val)
    except Exception:
        return None

def _get_expected_and_prompt(skill: Skill, question_id: str):
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
        expected = [it.text for it in items] 
        prompt = "Sắp xếp các từ thành câu đúng"
        return expected, prompt, t

    return "", "", t

def _compare_answer(expected, user_answer: str, skill_type: str) -> bool:
    if expected is None:
        return False

    if skill_type == "ordering" and isinstance(expected, (list, tuple)):
        exp_text = " ".join(map(str, expected))
        return _canon(exp_text) == _canon(user_answer)

    if isinstance(expected, (list, tuple)):
        exp_norms = {_canon_for_type(x, skill_type) for x in expected}
        return _canon_for_type(user_answer, skill_type) in exp_norms

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

REQUIRED_PCT = 80
def _compute_unlock_order(enrollment, topic_id, required_pct=REQUIRED_PCT):
    base = (
        Lesson.objects
        .filter(topic_id=topic_id)
        .annotate(
            total_skills=Count("skills", filter=Q(skills__is_active=True), distinct=True),
            done_skills=Count(
                "sessions__answers__skill",
                filter=Q(
                    sessions__enrollment=enrollment,
                    sessions__answers__is_correct=True,
                ),
                distinct=True,
            ),
        )
        .values("id", "order", "total_skills", "done_skills")
        .order_by("order", "id")
    )

    highest = 0
    for row in base:
        total = int(row["total_skills"] or 0)
        done  = int(row["done_skills"] or 0)
        pct   = (done * 100 // total) if total else 0
        if pct >= required_pct and row["order"] > highest:
            highest = row["order"]
    return (highest or 0) + 1

# ============ ViewSets ============

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
        if session.focus_skill_id:
            skills_qs = skills_qs.filter(id=session.focus_skill_id)
            
        data["skills"] = SkillSerializer(skills_qs, many=True).data
        return Response(data)

    @action(detail=False, methods=["post"], url_path="start")
    @transaction.atomic
    def start(self, request):
        s = StartSessionIn(data=request.data)
        s.is_valid(raise_exception=True)
        lesson = s.validated_data["lesson"]
        enrollment = s.validated_data["enrollment"]
        
        focus_skill_id = request.data.get("skill_id") 
        rec_id = request.data.get("recommendation_id")

        if enrollment.user_id != request.user.id:
            return Response({"detail": "Enrollment không thuộc user."}, status=403)
        if enrollment.language_id != lesson.topic.language_id:
            return Response({"detail": "Enrollment và Lesson không cùng ngôn ngữ."}, status=400)

        # Logic mở khóa bài học (nếu học full bài)
        if not focus_skill_id:
            tp, _ = TopicProgress.objects.get_or_create(
                enrollment=enrollment,
                topic_id=lesson.topic_id,
                defaults={"highest_completed_order": 0} 
            )
            highest = tp.highest_completed_order
            unlock_order = (highest or 0) + 1
            if lesson.order > unlock_order:
                return Response(
                    {
                        "detail": "Lesson đang bị khóa. Hãy hoàn thành ≥ %d%% bài trước." % REQUIRED_PCT,
                        "unlock_order": unlock_order,
                        "current_order": lesson.order,
                    },
                    status=403,
                )

        session = LessonSession.objects.create(
            user=request.user, lesson=lesson, enrollment=enrollment, status="in_progress", 
            focus_skill_id=focus_skill_id, 
            recommendation_id=rec_id
        )

        LearningInteraction.objects.create(
            user=request.user, enrollment=enrollment, lesson=lesson,
            action="start_lesson", success=True, duration_seconds=0, xp_earned=0, meta={}
        )

        skills_qs = _lesson_skills_qs(lesson.id)
        if focus_skill_id:
            skills_qs = skills_qs.filter(id=focus_skill_id)
            
        data = LessonSessionOut(session).data
        data["skills"] = SkillSerializer(skills_qs, many=True).data
        return Response(data, status=201)

    @action(detail=True, methods=["post"], url_path="complete")
    @transaction.atomic
    def complete(self, request, pk=None):
        session: LessonSession = self.get_object()
        c = CompleteSessionIn(data=request.data)
        c.is_valid(raise_exception=True)

        final_xp = c.validated_data.get("final_xp", session.xp_earned)

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

        session.complete_session(final_xp=final_xp)
        session.enrollment.mark_practiced()

        LearningInteraction.objects.create(
            user=request.user, enrollment=session.enrollment, lesson=session.lesson,
            action="complete_lesson", success=True,
            duration_seconds=session.duration_seconds, xp_earned=session.xp_earned, meta={}
        )

        try:
            unlock_order_new = _compute_unlock_order(
                session.enrollment, 
                session.lesson.topic_id, 
                required_pct=REQUIRED_PCT
            )
            highest_order_new = max(0, unlock_order_new - 1) 
            
            TopicProgress.objects.update_or_create(
                enrollment=session.enrollment,
                topic_id=session.lesson.topic_id,
                defaults={"highest_completed_order": highest_order_new}
            )
        except Exception as e:
            print(f"Failed to update TopicProgress: {e}")
        
        if final_xp and final_xp > 0:
            award_result = award_xp_from_lesson(
                user=request.user,
                source_id=session.id,   
                amount=final_xp
            )
        else:
            award_result = {"ok": True, "awarded": False, "reason": "lesson_xp_zero"}

        try:
            recalc_badges_for_user(
                request.user,
                limit_types=["lessons_completed", "total_xp", "streak_days"],
            )
        except Exception as e:
            print("[badges] recalc after lesson complete failed:", e)

        resp = LessonSessionOut(session).data
        resp["xp_award"] = award_result 
        return Response(resp, status=200)

    @action(detail=True, methods=["post"], url_path="cancel")
    @transaction.atomic
    def cancel(self, request, pk=None):
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
  
    @action(detail=True, methods=["post"], url_path="resume")
    def resume(self, request, pk=None):
        session = self.get_object()

        if session.status != "in_progress":
            return Response(
                {"detail": "Session này đã kết thúc hoặc bị hủy, không thể resume."},
                status=status.HTTP_400_BAD_REQUEST
            )

        session.last_activity = timezone.now()
        session.save(update_fields=["last_activity"])

        data = LessonSessionOut(session).data
        
        # Filter skill nếu session có focus
        skills_qs = _lesson_skills_qs(session.lesson_id)
        if session.focus_skill_id:
            skills_qs = skills_qs.filter(id=session.focus_skill_id)
            
        data["skills"] = SkillSerializer(skills_qs, many=True).data

        answered_count = session.answers.count()
        total_questions = skills_qs.count()
        
        next_index = answered_count

        data["resume_context"] = {
            "answered_count": answered_count,
            "total_questions": total_questions,
            "next_index": next_index,
            "is_finished_but_not_completed": answered_count >= total_questions
        }

        return Response(data, status=status.HTTP_200_OK)

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
        
        # Nếu session đang focus vào 1 skill, bắt buộc trả lời đúng skill đó
        if session.focus_skill_id and skill.id != session.focus_skill_id:
             return Response({"detail": "Skill này không thuộc phạm vi bài luyện tập."}, status=400)

        belongs = Skill.objects.filter(
            lessonskill__lesson_id=session.lesson_id, pk=skill.pk
        ).exists()
        if not belongs:
            return Response({"detail": "Skill không thuộc lesson của session."}, status=400)

        qid = v["question_id"]
        user_answer = v.get("user_answer", "")
        expected, prompt_text, skill_type = _get_expected_and_prompt(skill, qid)
        ok = _compare_answer(expected, user_answer, skill_type)

        expected_str = expected
        if isinstance(expected, (list, tuple)):
            expected_str = " ".join(expected)
        expected_str = str(expected_str or "")
        similarity = _seq_ratio(user_answer, expected_str)
        if skill_type in ["pron", "speaking", "writing", "fillgap"]:
            final_score = similarity
        else:
            final_score = 1.0 if ok else 0.0
        final_conf = 1.0 if user_answer.strip() else 0.0

        SessionAnswer.objects.create(
            session=session,
            skill=skill,
            question_id=qid,
            is_correct=ok,
            user_answer=user_answer,
            expected=(" ".join(expected) if (skill_type == "ordering" and isinstance(expected, (list, tuple))) else (expected or "")),
            meta={
                "client": "web",
                "calculated_score": final_score,
                **({"dur": v["duration_seconds"]} if v.get("duration_seconds") else {})
            }
        )

        session.total_questions += 1
        xp_gain = 0
        if ok:
            session.correct_answers += 1
            xp_gain = v.get("xp_on_correct", 5)
            session.xp_earned += xp_gain
        else:
            session.incorrect_answers += 1

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

        li = LearningInteraction.objects.create(
            user=request.user, enrollment=session.enrollment, lesson=session.lesson,
            skill=skill, action="practice_skill", value=final_score,
            success=ok, duration_seconds=v.get("duration_seconds") or 0,
            xp_earned=xp_gain, meta={"question_id": qid}
        )

        if session.recommendation_id:
            self._send_ai_feedback(session, skill, final_score, ok)

        mistake_id = None
        if not ok:
            m = Mistake.objects.create(
                user=request.user, enrollment=session.enrollment, interaction=li,
                lesson=session.lesson, skill=skill,
                source=v.get("source") or _map_source_from_skill(skill),
                prompt=v.get("question") or (prompt_text or ""),
                expected=(" ".join(expected) if (skill_type == "ordering" and isinstance(expected, (list, tuple))) else (expected or "")),
                user_answer=user_answer, error_detail={"question_id": qid},
                score=final_score,       
                confidence=final_conf
            )
            mistake_id = m.id
            uss, _ = UserSkillStats.objects.get_or_create(
                enrollment=session.enrollment, skill=skill, defaults={"status": "available"}
            )
            uss.mark_for_review()

        # Tính toán progress
        if session.focus_skill_id:
             skills_qs = _lesson_skills_qs(session.lesson_id).filter(id=session.focus_skill_id)
        else:
             skills_qs = _lesson_skills_qs(session.lesson_id)
             
        total_questions_count = skills_qs.count()
        current_answers_count = session.answers.count()
        is_finished = current_answers_count >= total_questions_count

        resp = {
            "session": LessonSessionOut(session).data,
            "xp_gain": xp_gain,
            "server_checked": True,
            "correct": ok,
            "is_finished": is_finished,
            "progress_status": f"{current_answers_count}/{total_questions_count}"
        }

        if expected is not None:
            resp["expected"] = (" ".join(expected) if (skill_type == "ordering" and isinstance(expected, (list, tuple))) else (expected or ""))
        if mistake_id:
            resp["mistake_id"] = mistake_id

        return Response(resp, status=200)

    def _send_ai_feedback(self, session, is_correct, xp_gain, time_spent):
        """Gửi feedback sang AI Service mỗi khi user trả lời"""
        ai_url = os.getenv('AI_SERVICE_BASE_URL', 'http://localhost:8001')
        url = f"{ai_url}/api/ai/feedbacks/"
        
        outcome_val = "completed" if is_correct else "failed"
        payload = {
            "recommendation": session.recommendation_id,
            "outcome": outcome_val,
            "time_spent": int(time_spent or 0),
            "xp_gain": int(xp_gain or 0)
        }
        
        headers = {}
        auth_header = self.request.META.get('HTTP_AUTHORIZATION')
        if auth_header:
            headers['Authorization'] = auth_header
        
        try:
            requests.post(url, json=payload, headers=headers, timeout=1)
        except Exception as e:
            print(f"[AI-FEEDBACK] Error forwarding to {url}: {e}")

@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def practice_overview(request):
    user = request.user
    raw_lang = request.GET.get("language")
    limit = int(request.GET.get("limit", 20))
    now = timezone.now()

    enr_qs = LanguageEnrollment.objects.select_related("language").filter(user=user)
    if raw_lang:
        lang_obj = Language.objects.filter(abbreviation=raw_lang).first()
        if not lang_obj and raw_lang.isdigit():
            lang_obj = Language.objects.filter(pk=int(raw_lang)).first()
        
        if lang_obj:
            enr_qs = enr_qs.filter(language=lang_obj)

    enrollment = enr_qs.first()
    if not enrollment:
        return Response({"detail": "Bạn chưa có Enrollment cho ngôn ngữ này."}, status=400)
    
    lang_obj = enrollment.language

    xp_today = DailyXP.objects.filter(
        user=user, date=timezone.localdate()
    ).values_list("xp", flat=True).first() or 0
    daily_goal = getattr(enrollment, "daily_goal", 60) 

    due_words_qs = (
        KnownWord.objects
        .filter(enrollment=enrollment, next_review__lte=now)
        .select_related("word")
        .order_by("next_review")[:limit]
    )

    known_ids = KnownWord.objects.filter(enrollment=enrollment).values_list("word", flat=True)
    words_qs = (
        Word.objects.filter(language=lang_obj)
        .exclude(id__in=known_ids)
        .order_by("id")[:limit] 
    )

    mistakes_raw = (
        Mistake.objects
        .filter(enrollment=enrollment)
        .values("source", "word", "word__text")
        .annotate(
            times=Count("id"),
            last_seen=Max("timestamp"),
        )
        .order_by("-times")[:limit]
    )
    mistakes_qs = []
    for row in mistakes_raw:
        mistakes_qs.append({
            "word_id": row.get("word"),              
            "word_text": row.get("word__text") or "",
            "error_type": row.get("source") or "",    
            "times": row.get("times") or 0,
            "last_seen": row.get("last_seen"),
        })

    weak_qs = (
        LearningInteraction.objects.filter(enrollment=enrollment, skill__isnull=False, value__isnull=False)
        .values(
            skill_tag=F("skill__type")
        )
        .annotate(
            accuracy=Avg("value")
        )
        .order_by("accuracy")[:5]
    )

    micro_qs = (
        LessonSession.objects.filter(enrollment=enrollment)
        .exclude(status="completed")
        .select_related("lesson")
        .order_by("-last_activity")[:limit]
    )

    sessions_qs = (
        PracticeSession.objects
        .filter(user=user) 
        .select_related("scenario")
        .order_by("-updated_at")[:limit]
    )

    data = {
        "enrollment": EnrollmentMiniSerializer(enrollment).data,
        "xp_today": int(xp_today or 0),
        "daily_goal": int(daily_goal or 0),
        "srs_due_words": KnownWordDueSerializer(due_words_qs, many=True).data,
        "word_suggestions": WordSuggestSerializer(words_qs, many=True).data,
        "common_mistakes": MistakeAggSerializer(mistakes_qs, many=True).data,
        "weak_skills": WeakSkillSerializer(weak_qs, many=True).data,
        "micro_lessons": MicroLessonSerializer(micro_qs, many=True).data,
        "speak_listen": PracticeSessionSerializer(sessions_qs, many=True).data,
    }
    
    return Response(data)


class SkillSessionViewSet(mixins.RetrieveModelMixin,
                          mixins.ListModelMixin,
                          viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = SkillSession.objects.all()

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return SkillSessionDetailOut
        if self.action == 'submit':
            return SkillSessionSubmitSerializer
        if self.action == 'start':
            return SkillSessionStartIn
        return SkillSessionOut

    def get_queryset(self):
        qs = super().get_queryset().filter(user=self.request.user)
        
        enrollment_id = self.request.query_params.get('enrollment')
        if enrollment_id:
            qs = qs.filter(enrollment_id=enrollment_id)

        status_param = self.request.query_params.get('status')
        if status_param:
            statuses = status_param.split(',')
            qs = qs.filter(status__in=statuses)
            
        return qs.order_by('-started_at')

    def retrieve(self, request, pk=None):
        session = get_object_or_404(SkillSession, pk=pk)
        if session.user_id != request.user.id:
            return Response({"detail": "Permission denied"}, status=403)
        serializer = SkillSessionDetailOut(session)
        return Response(serializer.data)

    @action(detail=False, methods=["post"], url_path="start")
    @transaction.atomic
    def start(self, request):
        s = SkillSessionStartIn(data=request.data)
        s.is_valid(raise_exception=True)
        skill = s.validated_data["skill"]
        enrollment = s.validated_data["enrollment"]
        lesson = s.validated_data.get("lesson")

        if enrollment.user_id != request.user.id:
            return Response({"detail": "Enrollment không thuộc user."}, status=403)

        lang_abbr = getattr(enrollment.language, "abbreviation", "").lower()
        if (skill.language_code or "").lower() != lang_abbr:
            return Response({"detail": "Enrollment và Skill không cùng ngôn ngữ."}, status=400)

        sess = SkillSession.objects.create(
            user=request.user,
            enrollment=enrollment,
            skill=skill,
            lesson=lesson,
            status="in_progress",
            meta={"source": "skill_session"},
        )
        return Response(SkillSessionOut(sess).data, status=201)

    @action(detail=False, methods=['post'], url_path='submit')
    def submit(self, request):
        ser = SkillSessionSubmitSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        
        data = ser.validated_data
        session_id = data['id']
        outcome = data['outcome'] 
        time_spent = data['time_spent']
        results = data.get('results', [])

        session = get_object_or_404(SkillSession, id=session_id)
        if session.user_id != request.user.id:
            return Response({"detail": "Permission denied"}, status=403)

        with transaction.atomic():
            if session.status == 'in_progress':
                session.status = 'completed' if outcome == 'completed' else 'failed'
                session.completed_at = timezone.now()
                session.duration_seconds = time_spent
                
                correct_cnt = sum(1 for r in results if r.get('isCorrect'))
                total_cnt = len(results) if results else 1
                session.avg_score = (correct_cnt / total_cnt) * 100
                
                base_xp = getattr(session.skill, 'xp_reward', 10)
                session.xp_earned = base_xp if outcome == 'completed' else 2
                
                session.save()
                
                if session.xp_earned > 0:
                    session.enrollment.total_xp = F('total_xp') + session.xp_earned
                    session.enrollment.save(update_fields=["total_xp"])

        try:
            self._report_to_ai_service(session, outcome, time_spent, session.xp_earned)
        except Exception as e:
            print(f"[AI-SYNC] Failed: {e}")

        return Response({
            "status": "success",
            "session_id": session.id,
            "xp_earned": session.xp_earned,
            "avg_score": session.avg_score
        }, status=status.HTTP_200_OK)


    @action(detail=True, methods=["post"], url_path="complete")
    @transaction.atomic
    def complete(self, request, pk=None):
        ss: SkillSession = self.get_object()
        skill_xp = getattr(ss.skill, 'xp_reward', 10) 
        ss.mark_completed(final_xp=skill_xp)
        if ss.xp_earned > 0:
            ss.enrollment.total_xp = F('total_xp') + ss.xp_earned
            ss.enrollment.save(update_fields=["total_xp"])
            ss.enrollment.refresh_from_db()

        try:
            recalc_badges_for_user(
                request.user,
                limit_types=["speaking_sessions", "total_xp"],
            )
        except Exception as e:
            print("[badges] Error:", e)

        return Response(SkillSessionOut(ss).data, status=200)

    @action(detail=True, methods=["post"], url_path="cancel")
    @transaction.atomic
    def cancel(self, request, pk=None):
        ss: SkillSession = self.get_object()
        if ss.status != "in_progress":
            return Response({"detail": "Chỉ hủy khi session đang 'in_progress'."}, status=400)
        
        as_failed = bool(request.data.get("as_failed") or False)
        ss.status = "failed" if as_failed else "abandoned"
        ss.completed_at = timezone.now()
        
        if ss.started_at:
            ss.duration_seconds = int((ss.completed_at - ss.started_at).total_seconds())
        
        ss.save(update_fields=["status", "completed_at", "duration_seconds"])
        return Response(SkillSessionOut(ss).data, status=200)

    @action(detail=True, methods=["get"], url_path="attempts")
    def attempts(self, request, pk=None):
        ss: SkillSession = self.get_object()
        qs = ss.attempts.order_by("-created_at")
        return Response(PronAttemptOut(qs, many=True).data, status=200)

    @action(detail=True, methods=["post"], url_path="save_attempt")
    def save_attempt(self, request, pk=None):
        session = self.get_object()
        d = request.data
        PronAttempt.objects.create(
            session=session,
            prompt_id_id=d.get("prompt_id"),
            expected_text=d.get("expected_text", ""),
            recognized=d.get("recognized", ""),
            score_overall=float(d.get("score_overall", 0)),
            words=d.get("words", []),
            details=d.get("details", {}),
            audio_path=d.get("audio_path", "")
        )
        session.refresh_from_db()
        return Response(SkillSessionOut(session).data, status=200)