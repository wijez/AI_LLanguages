# chat/management/commands/build_rag_index.py
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from pathlib import Path
import json, numpy as np
from chat.rag.embedders import make_embedder
from chat.rag.indexer import harvest_docs

class Command(BaseCommand):
    help = "Build RAG (NumPy cosine) từ Lesson.blocks."

    def add_arguments(self, parser):
        parser.add_argument("--topics", nargs="*", default=None)
        parser.add_argument("--out", default=str(settings.RAG_INDEX_DIR))

    def handle(self, *args, **opts):
        slugs = opts["topics"]; out = Path(opts["out"])
        docs, metas = harvest_docs(slugs)
        if not docs:
            raise CommandError("No documents found. Did you import skills/lessons?")
        emb = make_embedder()
        X = emb.encode(docs)
        out.mkdir(parents=True, exist_ok=True)
        np.save(out / "embeddings.npy", X)
        (out / "metas.json").write_text(json.dumps(metas, ensure_ascii=False), encoding="utf-8")
        (out / "docs.json").write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Built RAG (numpy): {len(docs)} docs → {out}"))
