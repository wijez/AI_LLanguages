import json
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from languages.models import Skill, Lesson, Topic

"""
JSON shape per item (array):
{
  "title": "string",
  "content": "string or object",
  "xp_reward": 2147483647,
  "duration_seconds": 2147483647,
  "skill": 0           # skill id OR skill title string (unique within a topic)
}
"""
from pathlib import Path
base = Path(r"D:\AI_LL\dataset")
base.mkdir(parents=True, exist_ok=True)

class Command(BaseCommand):
    help = "Load Lessons from a flat JSON array. Idempotent by (skill, title)."

    def add_arguments(self, parser):
        parser.add_argument("json_path", help="Path to lessons JSON (list of objects)")
        parser.add_argument("--topic", help="Optional topic id or slug to narrow skill lookup when using skill titles")
        parser.add_argument("--dry-run", action="store_true", help="Parse & validate only")

    def _resolve_skill(self, skill_ref, topic_hint=None):
        # skill_ref: int (id) or str (title); topic_hint optional id/slug narrows query
        if isinstance(skill_ref, int) or (isinstance(skill_ref, str) and str(skill_ref).isdigit()):
            try:
                return Skill.objects.get(id=int(skill_ref))
            except Skill.DoesNotExist:
                raise CommandError(f"Skill id={skill_ref} not found")
        elif isinstance(skill_ref, str):
            qs = Skill.objects.filter(title=skill_ref)
            if topic_hint is not None:
                # normalize hint to id or slug
                if isinstance(topic_hint, int) or (isinstance(topic_hint, str) and topic_hint.isdigit()):
                    qs = qs.filter(topic_id=int(topic_hint))
                else:
                    try:
                        t = Topic.objects.get(slug=topic_hint)
                    except Topic.DoesNotExist:
                        raise CommandError(
                            f"Topic hint '{topic_hint}' not found (when resolving skill '{skill_ref}')"
                        )
                    qs = qs.filter(topic=t)
            count = qs.count()
            if count == 0:
                raise CommandError(f"Skill title='{skill_ref}' not found")
            if count > 1:
                raise CommandError(
                    f"Skill title='{skill_ref}' is ambiguous; use --topic to disambiguate or provide skill id"
                )
            return qs.first()
        else:
            raise CommandError("Field 'skill' must be an integer id or a title string")

    def _normalize_content(self, value):
        if value is None:
            return {}
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            # try parse JSON string
            try:
                parsed = json.loads(value)
                if isinstance(parsed, (dict, list)):
                    return parsed
            except Exception:
                pass
            return {"raw": value}
        return {"raw": str(value)}

    @transaction.atomic
    def handle(self, *args, **opts):
        path = opts["json_path"]
        dry = opts["dry_run"]
        topic_hint = opts.get("topic")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise CommandError("Root must be a JSON array of lesson objects")

        created = 0
        updated = 0

        for i, item in enumerate(data, start=1):
            title = item.get("title")
            if not title:
                raise CommandError(f"[{i}] Missing 'title'")

            skill_ref = item.get("skill")
            if skill_ref is None:
                raise CommandError(f"[{i}] Missing 'skill' (id or title)")
            skill = self._resolve_skill(skill_ref, topic_hint=topic_hint)

            xp = int(item.get("xp_reward", 10))
            dur = int(item.get("duration_seconds", 120))
            content = self._normalize_content(item.get("content"))

            defaults = {"content": content, "xp_reward": xp, "duration_seconds": dur}

            lesson, was_created = Lesson.objects.get_or_create(
                skill=skill, title=title, defaults=defaults
            )

            if not was_created:
                changed_fields = []
                if lesson.xp_reward != xp:
                    lesson.xp_reward = xp
                    changed_fields.append("xp_reward")
                if lesson.duration_seconds != dur:
                    lesson.duration_seconds = dur
                    changed_fields.append("duration_seconds")
                if lesson.content != content:
                    lesson.content = content
                    changed_fields.append("content")

                if changed_fields and not dry:
                    lesson.save(update_fields=changed_fields)
                    updated += 1
            else:
                created += 1
                if dry:
                    # In atomic; raising will rollback (simulate dry-run)
                    raise CommandError("Dry-run cannot persist; re-run without --dry-run.")

        self.stdout.write(self.style.SUCCESS(
            f"Lessons loaded: +{created} created, ~{updated} updated."
        ))
