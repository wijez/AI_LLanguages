# server/recommend/management/commands/seed_demo_learning.py
from __future__ import annotations

import math
import random
from datetime import timedelta, date
from typing import List, Tuple

import numpy as np
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

# ====== MODELS (khớp với code bạn gửi) ======
from users.models import User
from progress.models import DailyXP
from languages.models import (
    Language, LanguageEnrollment, Topic, Skill, Lesson, UserSkillStats
)
from vocabulary.models import (
    Word, KnownWord, LearningInteraction, Mistake
)
from learning.models import LessonSession


# ========= Helpers =========
RNG = random.Random()
NRNG = np.random.default_rng()

def tznow():
    return timezone.now()

def fields(model) -> set:
    return {f.name for f in model._meta.fields}

def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ========= CLEAN =========
def clean_activity_only():
    """
    Xoá dữ liệu hoạt động demo (không xoá Language/Topic/Skill/Lesson/Word).
    """
    # Thứ tự tránh FK
    LearningInteraction.objects.all().delete()
    Mistake.objects.all().delete()
    LessonSession.objects.all().delete()
    DailyXP.objects.all().delete()
    KnownWord.objects.all().delete()
    UserSkillStats.objects.all().delete()
    LanguageEnrollment.objects.all().delete()
    # KHÔNG xoá User/Language/Topic/Skill/Lesson/Word


# ========= Ensure base entities =========
def ensure_language(abbreviation: str = "en", name: str = "English", native: str = "English", direction: str = "LTR") -> Language:
    lang = Language.objects.filter(abbreviation=abbreviation).first()
    if lang:
        return lang
    return Language.objects.create(
        name=name,
        abbreviation=abbreviation,
        native_name=native,
        direction=direction,
    )

def ensure_topics_skills_lessons(lang: Language, topics_count: int = 6, skills_per_topic: int = 6, lessons_per_skill: int = 8) -> Tuple[List[int], List[int]]:
    """
    Tạo chuỗi Topic -> Skill -> Lesson đầy đủ cho một Language.
    Trả về (skill_ids, lesson_ids)
    """
    # Topics
    topic_ids: List[int] = list(Topic.objects.filter(language=lang).values_list("id", flat=True))
    need_topics = max(0, topics_count - len(topic_ids))
    if need_topics:
        tbulk = []
        start = len(topic_ids)
        for i in range(need_topics):
            tbulk.append(Topic(
                language=lang,
                slug=f"topic-{start + i + 1}",
                title=f"Topic {start + i + 1}",
                description="Demo topic",
                order=start + i + 1,
                golden=(i == 0)
            ))
        Topic.objects.bulk_create(tbulk, batch_size=200)
        topic_ids = list(Topic.objects.filter(language=lang).order_by("order").values_list("id", flat=True))[:topics_count]
    else:
        # giới hạn theo yêu cầu
        topic_ids = topic_ids[:topics_count]

    # Skills
    skill_ids: List[int] = list(Skill.objects.filter(topic_id__in=topic_ids).values_list("id", flat=True))
    target_skills = topics_count * skills_per_topic
    need_skills = max(0, target_skills - len(skill_ids))
    if need_skills:
        sbulk = []
        existing = len(skill_ids)
        for ti, topic_id in enumerate(topic_ids):
            # mỗi topic tạo thêm thiếu số skill
            current = Skill.objects.filter(topic_id=topic_id).count()
            to_make = max(0, skills_per_topic - current)
            for j in range(to_make):
                order = current + j + 1
                sbulk.append(Skill(
                    topic_id=topic_id,
                    title=f"Skill T{ti+1}-{order}",
                    description="Demo skill",
                    order=order
                ))
        if sbulk:
            Skill.objects.bulk_create(sbulk, batch_size=500)
        skill_ids = list(Skill.objects.filter(topic_id__in=topic_ids).values_list("id", flat=True))

    # Lessons
    lesson_ids: List[int] = list(Lesson.objects.filter(skill_id__in=skill_ids).values_list("id", flat=True))
    target_lessons = len(skill_ids) * lessons_per_skill
    need_lessons = max(0, target_lessons - len(lesson_ids))
    if need_lessons:
        lbulk = []
        for sid in skill_ids:
            current = Lesson.objects.filter(skill_id=sid).count()
            to_make = max(0, lessons_per_skill - current)
            for k in range(to_make):
                lbulk.append(Lesson(
                    skill_id=sid,
                    title=f"Lesson S{sid}-{current + k + 1}",
                    content={"demo": True},
                    xp_reward=10 + RNG.randint(0, 40),
                    duration_seconds=120 + RNG.randint(0, 600)
                ))
        if lbulk:
            Lesson.objects.bulk_create(lbulk, batch_size=1000)
        lesson_ids = list(Lesson.objects.filter(skill_id__in=skill_ids).values_list("id", flat=True))

    return skill_ids, lesson_ids

def ensure_words(lang: Language, target_words: int = 3000) -> List[int]:
    exist_ids = list(Word.objects.filter(language=lang).values_list("id", flat=True))
    need = max(0, target_words - len(exist_ids))
    if need:
        wbulk = []
        start = len(exist_ids)
        for i in range(need):
            text = f"word_{start + i + 1}"
            wbulk.append(Word(
                language=lang,
                text=text,
                normalized=text,
                part_of_speech=RNG.choice(["noun", "verb", "adj", "adv"])
            ))
        Word.objects.bulk_create(wbulk, batch_size=1000)
        exist_ids = list(Word.objects.filter(language=lang).values_list("id", flat=True))
    return exist_ids


def ensure_users(n: int) -> List[int]:
    current = list(User.objects.values_list("id", flat=True))
    need = max(0, n - len(current))
    ubulk = []
    start = len(current)
    for i in range(need):
        uname = f"demo_user_{start + i + 1}"
        ubulk.append(User(username=uname, email=f"{uname}@example.com"))
    if ubulk:
        User.objects.bulk_create(ubulk, batch_size=500)
    return list(User.objects.values_list("id", flat=True))[:n]


def ensure_enrollments(user_ids: List[int], lang: Language) -> List[int]:
    # unique (user, language)
    existing = set(LanguageEnrollment.objects.filter(language=lang).values_list("user_id", flat=True))
    new_bulk = []
    for uid in user_ids:
        if uid in existing:
            continue
        new_bulk.append(LanguageEnrollment(
            user_id=uid,
            language=lang,
            level=RNG.randint(0, 5),
            total_xp=RNG.randint(0, 5000),
            streak_days=RNG.randint(0, 60),
            last_practiced=tznow() - timedelta(days=RNG.randint(0, 30))
        ))
    if new_bulk:
        LanguageEnrollment.objects.bulk_create(new_bulk, batch_size=1000)
    # trả về toàn bộ enrollment id của ngôn ngữ này cho các user đã chọn
    return list(LanguageEnrollment.objects.filter(user_id__in=user_ids, language=lang).values_list("id", flat=True))


# ========= Seeding per-entity =========
def seed_daily_xp(user_id: int, days: int = 60):
    """
    Tạo DailyXP ngẫu nhiên cho N ngày gần đây cho user.
    Idempotent: nếu đã có (user, date) thì bỏ qua, tránh UniqueViolation.
    """
    from datetime import date as date_cls
    from progress.models import DailyXP

    today = tznow().date()
    start_date = today - timedelta(days=days)

    # Lấy các ngày đã tồn tại để skip
    existing = set(
        DailyXP.objects.filter(user_id=user_id, date__gte=start_date)
        .values_list("date", flat=True)
    )

    rows = []
    cur = start_date
    while cur <= today:
        if cur not in existing:
            # sinh XP ngẫu nhiên (0…60) với xác suất 20% là 0 để tạo ngày nghỉ
            xp = 0 if RNG.random() < 0.2 else RNG.randint(5, 60)
            if xp > 0:
                rows.append(DailyXP(user_id=user_id, date=cur, xp=xp))
        cur += timedelta(days=1)

    if rows:
        # Django >= 3.2: tham số ignore_conflicts
        DailyXP.objects.bulk_create(rows, batch_size=1000, ignore_conflicts=True)

def seed_known_words(enrollment_id: int, word_ids: list[int], n_words: int = 200):
    """
    Tạo KnownWord cho 1 enrollment:
      - Idempotent: bỏ qua (enrollment, word) đã tồn tại
      - Không chọn trùng word trong cùng 1 batch
    """
    from vocabulary.models import KnownWord
    from django.utils import timezone

    # Tập word đã có sẵn cho enrollment này
    existing_word_ids = set(
        KnownWord.objects.filter(enrollment_id=enrollment_id)
        .values_list("word_id", flat=True)
    )

    # Pool ứng viên = word_ids chưa có
    remaining = list(set(word_ids) - existing_word_ids)
    if not remaining:
        return

    # Lấy tối đa n_words, không trùng lặp
    k = min(n_words, len(remaining))
    # RNG.sample để không lặp trong batch
    picked = RNG.sample(remaining, k=k)

    now = timezone.now()
    rows = []
    for wid in picked:
        # dữ liệu ban đầu nhẹ nhàng, có thể random một ít
        rows.append(
            KnownWord(
                enrollment_id=enrollment_id,
                word_id=wid,
                score=RNG.uniform(0, 100),
                ease_factor=round(RNG.uniform(1.3, 3.0), 3),
                interval_days=RNG.randint(1, 30),
                repetitions=RNG.randint(0, 10),
                next_review=now + timedelta(days=RNG.randint(0, 30)),
                status=RNG.choice(["new", "learning", "reviewing", "mastered"]),
                total_reviews=RNG.randint(0, 30),
                correct_reviews=RNG.randint(0, 30),
                times_forgotten=RNG.randint(0, 5),
            )
        )

    if rows:
        # Phòng khi có race/đụng nhau vẫn không nổ
        KnownWord.objects.bulk_create(rows, batch_size=1000, ignore_conflicts=True)


def seed_interactions_and_mistakes(user_id: int, enrollment_id: int, lesson_ids: List[int], word_ids: List[int], days: int = 30):
    actions = ["start_lesson", "complete_lesson", "review_word", "practice_skill"]
    sources = ["pronunciation", "grammar", "vocab", "listening", "spelling"]

    n_inter = RNG.randint(days, days * 3)
    base = tznow() - timedelta(days=days)
    li_rows, mk_rows = [], []
    for _ in range(n_inter):
        ts = base + timedelta(minutes=RNG.randint(0, days * 24 * 60))
        action = RNG.choice(actions)
        success = RNG.random() < 0.8
        lesson_id = RNG.choice(lesson_ids) if action in ("start_lesson", "complete_lesson", "practice_skill") else None
        word_id = RNG.choice(word_ids) if action == "review_word" else None

        li = LearningInteraction(
            user_id=user_id,
            enrollment_id=enrollment_id,
            lesson_id=lesson_id,
            word_id=word_id,
            # skill optional (bạn có thể gán từ lesson)
            skill_id=None,
            action=action,
            success=success,
            duration_seconds=RNG.randint(10, 300),
            xp_earned=RNG.randint(0, 50),
            created_at=ts
        )
        li_rows.append(li)

        # đôi khi phát sinh mistake
        if RNG.random() < 0.35:
            prompt = "Say the sentence: 'The quick brown fox jumps over the lazy dog.'"
            mk = Mistake(
                user_id=user_id,
                enrollment_id=enrollment_id,
                interaction=None,  # sẽ không set kèm liên kết vì bulk_create chưa có id
                lesson_id=lesson_id,
                word_id=word_id,
                source=RNG.choice(sources),
                prompt=prompt,
                expected="The quick brown fox jumps over the lazy dog.",
                user_answer=" ".join(RNG.choice(["The", "quick", "brown", "fox", "jumps", "over", "lazy", "dog"]) for _ in range(6)),
                mispronounced_words=None,
                error_detail=None,
                score=float(clamp01(NRNG.normal(0.7, 0.15))),
                confidence=float(clamp01(NRNG.normal(0.8, 0.1))),
                timestamp=ts,
            )
            mk_rows.append(mk)

    if li_rows:
        LearningInteraction.objects.bulk_create(li_rows, batch_size=1000)
    if mk_rows:
        Mistake.objects.bulk_create(mk_rows, batch_size=1000)


def seed_sessions(user_id: int, enrollment_id: int, lessons: List[Lesson], days: int = 60):
    """
    Seed LessonSession (bắt buộc có user, enrollment, lesson; skill tự gán từ lesson.skill).
    NOTE: bulk_create không gọi save(), nên phải tự sinh session_id (unique) trước khi insert.
    """
    if not lessons:
        return
    import uuid

    base = tznow() - timedelta(days=days)
    rows = []
    n = RNG.randint(days, int(days * 2.2))

    for _ in range(n):
        lesson = RNG.choice(lessons)
        skill_id = lesson.skill_id
        started = base + timedelta(minutes=RNG.randint(0, days * 24 * 60))
        status = RNG.choices(
            ["in_progress", "completed", "failed", "abandoned"],
            weights=[0.10, 0.70, 0.05, 0.15],
            k=1
        )[0]
        completed = None
        if status in ("completed", "failed"):
            completed = started + timedelta(minutes=RNG.randint(2, 40))

        total_q = RNG.randint(5, 15)
        correct = RNG.randint(math.floor(total_q * 0.5), total_q)
        incorrect = total_q - correct
        perfect = (incorrect == 0 and status == "completed")

        rows.append(LessonSession(
            user_id=user_id,
            enrollment_id=enrollment_id,
            lesson_id=lesson.id,
            skill_id=skill_id,
            status=status,
            # TỰ GÁN UUID vì bulk_create không gọi save()
            session_id=str(uuid.uuid4()),
            started_at=started,
            completed_at=completed,
            last_activity=completed or started,
            correct_answers=correct,
            incorrect_answers=incorrect,
            total_questions=total_q,
            xp_earned=RNG.randint(5, 40) + (10 if perfect else 0),
            perfect_lesson=perfect,
            speed_bonus=RNG.randint(0, 15),
            combo_bonus=RNG.randint(0, 15),
            duration_seconds=RNG.randint(60, 1800),
            answers_data={"demo": True},
        ))

    if rows:
        LessonSession.objects.bulk_create(rows, batch_size=1000)



def seed_user_skill_stats(enrollment_id: int, skills: List[Skill], max_per_enr: int = 10):
    """
    Tạo một số UserSkillStats cho mỗi enrollment (unique enrollment+skill).
    Idempotent:
      - Bỏ qua các skill đã có sẵn cho enrollment này
      - Không chọn trùng trong batch
      - Dùng ignore_conflicts=True để phòng race/đụng lẫn
    """
    from languages.models import UserSkillStats

    # Skill đã có sẵn cho enrollment này
    existing_skill_ids = set(
        UserSkillStats.objects.filter(enrollment_id=enrollment_id)
        .values_list("skill_id", flat=True)
    )

    # Chỉ lấy các skill CHƯA có
    candidate_skills = [sk for sk in skills if sk.id not in existing_skill_ids]
    if not candidate_skills:
        return

    take = min(max_per_enr, len(candidate_skills))
    chosen = RNG.sample(candidate_skills, k=take)

    rows = []
    now = tznow()
    for sk in chosen:
        level = RNG.randint(0, 5)
        lreq = 5 + (level * 2)
        ldone = RNG.randint(0, lreq)
        status = RNG.choice(["locked", "available", "in_progress", "completed", "mastered"])
        if status == "mastered":
            level = max(level, 5)

        rows.append(UserSkillStats(
            enrollment_id=enrollment_id,
            skill_id=sk.id,
            xp=RNG.randint(0, 800),
            total_lessons_completed=RNG.randint(0, 60),
            last_practiced=now - timedelta(days=RNG.randint(0, 30)),
            proficiency_score=float(min(100.0, level * 20 + RNG.randint(0, 20))),
            level=level,
            lessons_completed_at_level=ldone,
            lessons_required_for_next=lreq,
            needs_review=RNG.random() < 0.2,
            review_reminder_date=(now.date() + timedelta(days=RNG.randint(0, 14))) if RNG.random() < 0.2 else None,
            status=status,
            unlocked_at=now - timedelta(days=RNG.randint(10, 90)) if status != "locked" else None,
            first_completed_at=now - timedelta(days=RNG.randint(5, 80)) if status in ("completed", "mastered") else None,
            mastered_at=now - timedelta(days=RNG.randint(1, 60)) if status == "mastered" else None,
        ))

    if rows:
        UserSkillStats.objects.bulk_create(rows, batch_size=500, ignore_conflicts=True)






# ========= Command =========
class Command(BaseCommand):
    help = "Seed demo learning data fully consistent with your models (FKs NOT NULL handled)."

    def add_arguments(self, parser):
        parser.add_argument("--users", type=int, default=60)
        parser.add_argument("--days", type=int, default=60)
        parser.add_argument("--target_days", type=int, default=7)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--clean", action="store_true")
        parser.add_argument("--lang", type=str, default="en", help="Language abbreviation (default: en)")

    @transaction.atomic
    def handle(self, *args, **opts):
        # seeds
        seed_val = int(opts["seed"])
        RNG.seed(seed_val)
        np.random.seed(seed_val)

        users_n = int(opts["users"])
        days = int(opts["days"])
        target_days = int(opts["target_days"])
        do_clean = bool(opts["clean"])
        lang_abbr = str(opts["lang"])

        if do_clean:
            self.stdout.write("Cleaning previous demo activity data...")
            clean_activity_only()

        # language + curriculum
        lang = ensure_language(abbreviation=lang_abbr)
        skill_ids, lesson_ids = ensure_topics_skills_lessons(lang, topics_count=6, skills_per_topic=6, lessons_per_skill=8)
        if not lesson_ids:
            self.stdout.write(self.style.ERROR("No lessons available → cannot seed sessions."))
            return
        lessons = list(Lesson.objects.filter(id__in=lesson_ids))
        skills = list(Skill.objects.filter(id__in=skill_ids))
        word_ids = ensure_words(lang, target_words=3000)

        # users + enrollments
        user_ids = ensure_users(users_n)
        self.stdout.write(f"Users ready: {len(user_ids)}")
        enr_ids = ensure_enrollments(user_ids, lang)
        self.stdout.write(f"Enrollments created/ensured: {len(enr_ids)}")

        # map user → their enrollment id (1-1 vì unique user+language)
        enr_map = dict(LanguageEnrollment.objects.filter(id__in=enr_ids).values_list("user_id", "id"))

        # per-user: DailyXP
        for uid in user_ids:
            seed_daily_xp(uid, min(60, days))

        # per-enrollment: words/interactions/mistakes/sessions/stats
        for uid in user_ids:
            eid = enr_map.get(uid)
            if not eid:
                continue
            # Known words
            seed_known_words(eid, word_ids, n_words=RNG.randint(120, 300))
            # Interactions + mistakes (30d gần đây)
            seed_interactions_and_mistakes(uid, eid, lesson_ids, word_ids, days=min(30, days))
            # Sessions
            seed_sessions(uid, eid, lessons, days=days)
            # UserSkillStats
            seed_user_skill_stats(eid, skills, max_per_enr=12)

        self.stdout.write(self.style.SUCCESS("✅ Demo data seeded successfully."))
