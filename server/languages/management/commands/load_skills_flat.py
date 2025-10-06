# languages/management/commands/load_skills_flat.py
import json
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from languages.models import Topic, Skill
from pathlib import Path

"""
JSON shape per item (array):
{
  "title": "string",
  "description": "string",
  "order": 2147483647,
  "topic": 0            # topic id OR topic slug (string)
}
"""
base = Path(r"D:\AI_LL\dataset")
base.mkdir(parents=True, exist_ok=True)

class Command(BaseCommand):
    help = "Load Skills from a flat JSON array. Idempotent by (topic, title)."

    def add_arguments(self, parser):
        parser.add_argument("json_path", help="Path to skills JSON (list of objects)")
        parser.add_argument("--dry-run", action="store_true", help="Parse & validate only")

    def _resolve_topic(self, topic_ref):
        # topic_ref: int (id) or str (slug)
        if isinstance(topic_ref, int):
            try:
                return Topic.objects.get(id=topic_ref)
            except Topic.DoesNotExist:
                raise CommandError(f"Topic id={topic_ref} not found")
        elif isinstance(topic_ref, str):
            qs = Topic.objects.filter(slug=topic_ref)
            count = qs.count()
            if count == 0:
                raise CommandError(f"Topic slug='{topic_ref}' not found")
            if count > 1:
                raise CommandError(f"Topic slug='{topic_ref}' is ambiguous across languages")
            return qs.first()
        else:
            raise CommandError("Field 'topic' must be an integer id or a slug string")

    @transaction.atomic
    def handle(self, *args, **opts):
        path = opts["json_path"]
        dry = opts["dry_run"]

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise CommandError("Root must be a JSON array of skill objects")

        created = 0
        updated = 0

        for i, item in enumerate(data, start=1):
            title = item.get("title")
            if not title:
                raise CommandError(f"[{i}] Missing 'title'")

            topic_ref = item.get("topic")
            if topic_ref is None:
                raise CommandError(f"[{i}] Missing 'topic' (id or slug)")
            topic = self._resolve_topic(topic_ref)

            defaults = {
                "description": item.get("description", ""),
                "order": item.get("order", 0),
            }

            skill, was_created = Skill.objects.get_or_create(
                topic=topic, title=title, defaults=defaults
            )

            if not was_created:
                changed = False
                if skill.description != defaults["description"]:
                    skill.description = defaults["description"]
                    changed = True
                if skill.order != defaults["order"]:
                    skill.order = defaults["order"]
                    changed = True
                if changed and not dry:
                    skill.save(update_fields=["description", "order"])
                    updated += 1
            else:
                created += 1
                if dry:
                    # Đang ở trong atomic, raise để rollback (chỉ kiểm thử)
                    raise CommandError("Dry-run cannot persist; re-run without --dry-run.")

        self.stdout.write(self.style.SUCCESS(
            f"Skills loaded: +{created} created, ~{updated} updated."
        ))
