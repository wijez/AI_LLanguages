
import json
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from languages.models import Language, Topic, Skill, Lesson

class Command(BaseCommand):
    help = "Load a Duolingo-style course JSON (topics → skills → lessons). Idempotent."

    def add_arguments(self, parser):
        parser.add_argument("json_path", help="Path to course JSON")
        parser.add_argument("--lang", default=None, help="Override language abbreviation in JSON")

    @transaction.atomic
    def handle(self, *args, **opts):
        path = opts["json_path"]
        lang_override = opts.get("lang")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        lang_abbr = lang_override or data["language"]["abbreviation"]
        lang_name = data["language"].get("name", lang_abbr.upper())
        native_name = data["language"].get("native_name", "")
        direction = data["language"].get("direction", "LTR")

        language, _ = Language.objects.get_or_create(
            abbreviation=lang_abbr,
            defaults={"name": lang_name, "native_name": native_name, "direction": direction},
        )

        created_topics = 0
        created_skills = 0
        created_lessons = 0

        for t in data["topics"]:
            topic, t_created = Topic.objects.get_or_create(
                language=language,
                slug=t["slug"],
                defaults={
                    "title": t["title"],
                    "description": t.get("description", ""),
                    "order": t.get("order", 0),
                },
            )
            if not t_created:
                # update basic fields if changed
                topic.title = t["title"]
                topic.description = t.get("description", "")
                topic.order = t.get("order", topic.order)
                topic.save(update_fields=["title", "description", "order"])
            created_topics += int(t_created)

            for idx_s, s in enumerate(t.get("skills", []), start=1):
                skill, s_created = Skill.objects.get_or_create(
                    topic=topic,
                    title=s["title"],
                    defaults={
                        "description": s.get("description", ""),
                        "order": s.get("order", idx_s),
                    },
                )
                if not s_created:
                    skill.description = s.get("description", skill.description)
                    skill.order = s.get("order", skill.order)
                    skill.save(update_fields=["description", "order"])
                created_skills += int(s_created)

                for idx_l, l in enumerate(s.get("lessons", []), start=1):
                    lesson, l_created = Lesson.objects.get_or_create(
                        skill=skill,
                        title=l["title"],
                        defaults={
                            "content": l.get("content", {}),
                            "xp_reward": l.get("xp_reward", 10),
                            "duration_seconds": l.get("duration_seconds", 120),
                        },
                    )
                    if not l_created:
                        lesson.content = l.get("content", lesson.content)
                        lesson.xp_reward = l.get("xp_reward", lesson.xp_reward)
                        lesson.duration_seconds = l.get("duration_seconds", lesson.duration_seconds)
                        lesson.save(update_fields=["content", "xp_reward", "duration_seconds"])
                    created_lessons += int(l_created)

        self.stdout.write(self.style.SUCCESS(
            f"Done. topics(+{created_topics}), skills(+{created_skills}), lessons(+{created_lessons}) in language '{language.abbreviation}'."
        ))
