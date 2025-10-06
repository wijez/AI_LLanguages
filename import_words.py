import json
from django.db import transaction
from server.vocabulary.models import Word, WordRelation
from server.languages.models import Languages 

# Đường dẫn dataset
WORDS_PATH = "D:/AI_LL/dataset/verbs_dataset/words.json"
RELATIONS_PATH = "D:/AI_LL/dataset/verbs_dataset/words_relations.json"


@transaction.atomic
def run():
    # 1. Import words.json
    with open(WORDS_PATH, "r", encoding="utf-8") as f:
        words_data = json.load(f)

    print(f"📥 Importing {len(words_data)} words...")

    word_map = {}  # (lang, text) -> Word instance

    for item in words_data:
        lang_abbr = item["language"]
        text = item["text"].strip()
        normalized = item.get("normalized", text.lower())
        pos = item.get("part_of_speech", "")

        try:
            lang = Language.objects.get(abbreviation=lang_abbr)
        except Language.DoesNotExist:
            print(f"⚠️ Language {lang_abbr} not found, skipping word {text}")
            continue

        word, created = Word.objects.get_or_create(
            language=lang,
            text=text,
            defaults={
                "normalized": normalized,
                "part_of_speech": pos
            }
        )
        if created:
            print(f"✅ Inserted word: {text} ({lang_abbr})")
        word_map[(lang_abbr, text.lower())] = word

    # 2. Import relations.json
    with open(RELATIONS_PATH, "r", encoding="utf-8") as f:
        rel_data = json.load(f)

    print(f"\n📥 Importing {len(rel_data)} relations...")

    created_count = 0
    skipped_count = 0

    for rel in rel_data:
        lang_abbr = rel["language"]
        word_text = rel["word_text"].lower()
        related_text = rel["related_text"].lower()
        rel_type = rel["relation_type"]

        word = word_map.get((lang_abbr, word_text))
        related = word_map.get((lang_abbr, related_text))

        if not word or not related:
            print(f"⚠️ Missing word in relation: {word_text} → {related_text}")
            skipped_count += 1
            continue

        _, created = WordRelation.objects.get_or_create(
            word=word,
            related=related,
            relation_type=rel_type
        )
        if created:
            created_count += 1

    print(f"\n✅ Done! {created_count} relations inserted, {skipped_count} skipped.")
