import csv, json, pathlib
from typing import List, Dict, Any
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from languages.models import Language, Topic, Skill, Lesson

def _read_csv(path: str) -> List[Dict[str, Any]]:
    p = pathlib.Path(path)
    if not p.exists():
        raise CommandError(f"CSV not found: {p}")
    # Đọc UTF-8 BOM để bảo toàn dấu tiếng Việt
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def _read_json(path: str) -> Any:
    p = pathlib.Path(path)
    if not p.exists():
        raise CommandError(f"JSON not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

class Command(BaseCommand):
    help = "Import 'Cửa 1 – Mời khách xơi nước' dataset vào Language/Topic/Skill/Lesson.content"

    def add_arguments(self, parser):
        parser.add_argument("--language", default="en", help="Language abbreviation, e.g. en")
        parser.add_argument("--language-name", default=None)     # <- optional
        parser.add_argument("--language-native", default=None)  
        parser.add_argument("--topic-slug", default="cua-1-moi-khach-xoi-nuoc")
        parser.add_argument("--topic-title", default="Cửa 1 – Mời khách xơi nước")
        parser.add_argument("--topic-desc", default="Mời nước: welcome, coffee or tea?, water please, thank you, goodbye")
        parser.add_argument("--skill-title", default="Serve drinks & greetings")
        parser.add_argument("--skill-desc", default="Key phrases for welcoming guests and offering drinks")
        parser.add_argument("--lesson-title", default="Cửa 1 – Mời khách xơi nước")
        parser.add_argument("--phrases-csv", required=True)
        parser.add_argument("--qna-csv", required=True)
        parser.add_argument("--dialogues-json", required=True)
        parser.add_argument("--topic-order", type=int, default=1)
        parser.add_argument("--skill-order", type=int, default=1)
        parser.add_argument("--xp-reward", type=int, default=10)
        parser.add_argument("--duration", type=int, default=180)

    def handle(self, *args, **opts):
        # --- Chuẩn hóa keys ---
        abbr = (opts.get("language") or "en").lower()
        name = opts.get("language_name")
        native = opts.get("language_native")
        topic_slug = opts.get("topic_slug") or "cua-1-moi-khach-xoi-nuoc"
        topic_title = opts.get("topic_title") or "Cửa 1 – Mời khách xơi nước"
        topic_desc = opts.get("topic_desc") or "Mời nước: welcome, coffee or tea?, water please, thank you, goodbye"
        skill_title = opts.get("skill_title") or "Serve drinks & greetings"
        skill_desc = opts.get("skill_desc") or "Key phrases for welcoming guests and offering drinks"
        lesson_title = opts.get("lesson_title") or "Cửa 1 – Mời khách xơi nước"

        phrases_csv = opts["phrases_csv"]
        qna_csv = opts["qna_csv"]
        dialogues_json = opts["dialogues_json"]

        topic_order = int(opts.get("topic_order") or 1)
        skill_order = int(opts.get("skill_order") or 1)
        xp_reward = int(opts.get("xp_reward") or 10)
        duration = int(opts.get("duration") or 180)

        # --- Mặc định tên/ngôn ngữ nếu không truyền ---
        LANG_MAP = {
            "en": ("English", "English", "LTR"),
            "vi": ("Vietnamese", "Tiếng Việt", "LTR"),
            "ar": ("Arabic", "العربية", "RTL"),
            # bổ sung nếu cần
        }
        if not name or not native:
            m = LANG_MAP.get(abbr)
            if m:
                name = name or m[0]
                native = native or m[1]
                direction = m[2]
            else:
                name = name or abbr.upper()
                native = native or abbr.upper()
                direction = "LTR"
        else:
            direction = "LTR"

        # 1) Ensure language
        lang, _ = Language.objects.get_or_create(
            abbreviation=abbr,
            defaults=dict(name=name, native_name=native, direction=direction),
        )

        # 2) Ensure topic
        topic, created_topic = Topic.objects.get_or_create(
            language=lang, slug=topic_slug,
            defaults=dict(title=topic_title, description=topic_desc, order=topic_order, golden=False),
        )
        if not created_topic:
            changed = False
            if topic.title != topic_title:
                topic.title = topic_title; changed = True
            if topic.description != topic_desc:
                topic.description = topic_desc; changed = True
            if topic.order != topic_order:
                topic.order = topic_order; changed = True
            if changed:
                topic.save()

        # 3) Ensure skill
        skill, created_skill = Skill.objects.get_or_create(
            topic=topic, title=skill_title,
            defaults=dict(description=skill_desc, order=skill_order)
        )
        if not created_skill:
            changed = False
            if skill.description != skill_desc:
                skill.description = skill_desc; changed = True
            if skill.order != skill_order:
                skill.order = skill_order; changed = True
            if changed:
                skill.save()

        # 4) Load data files
        phrases_raw = _read_csv(phrases_csv)
        qna_raw = _read_csv(qna_csv)
        dialogues_raw = _read_json(dialogues_json)

        # 5) Normalize → Lesson.content JSON
        phrase_bank = [
            {
                "id": r.get("id"),
                "level": r.get("level", "A1"),
                "intent": (r.get("intent") or "").strip(),
                "en": (r.get("english") or "").strip(),
                "vi": (r.get("vietnamese") or "").strip(),
                "notes": (r.get("notes") or "").strip(),
                "tags": [t.strip() for t in (r.get("context_tags") or "").split(",") if t.strip()],
            }
            for r in phrases_raw
        ]
        qna = [
            {
                "id": r.get("id"),
                "level": r.get("level", "A1"),
                "intent": (r.get("intent") or "").strip(),
                "q_en": (r.get("question_en") or "").strip(),
                "a_en": (r.get("answer_en") or "").strip(),
                "q_vi": (r.get("question_vi") or "").strip(),
                "a_vi": (r.get("answer_vi") or "").strip(),
            }
            for r in qna_raw
        ]
        dialogues = dialogues_raw

        content = {
            "version": "1.0",
            "topic_slug": topic.slug,
            "skill_title": skill.title,
            "lesson_title": lesson_title,
            "sections": [
                {"type": "phrase_bank", "items": phrase_bank},
                {"type": "qna_pairs",   "items": qna},
                {"type": "dialogues",   "items": dialogues},
            ],
            "meta": {
                "source": "cua1_import",
                "en_vi_bilingual": True,
                "intents": sorted(set([p["intent"] for p in phrase_bank if p.get("intent")])),
                "tags": sorted({t for p in phrase_bank for t in p.get("tags", [])}),
            }
        }

        # 6) Upsert lesson
        lesson, created_lesson = Lesson.objects.get_or_create(
            skill=skill, title=lesson_title,
            defaults=dict(content=content, xp_reward=xp_reward, duration_seconds=duration)
        )
        if not created_lesson:
            lesson.content = content
            lesson.xp_reward = xp_reward
            lesson.duration_seconds = duration
            lesson.save()

        self.stdout.write(self.style.SUCCESS(
            f"Imported into Lesson id={lesson.id} (created={created_lesson}) "
            f"→ Language={lang.abbreviation}, Topic={topic.slug}, Skill={skill.title}"
        ))
