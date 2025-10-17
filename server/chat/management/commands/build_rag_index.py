from django.core.management.base import BaseCommand
from django.conf import settings
from pathlib import Path
import json, numpy as np

from chat.rag.indexer import harvest_docs
from chat.rag.embedders import make_embedder

class Command(BaseCommand):
    help = "Build RAG index from lessons into RAG_INDEX_DIR"

    def add_arguments(self, parser):
        parser.add_argument('--topics', nargs='*', default=None, help='Topic slugs filter')

    def handle(self, *args, **opts):
        out = Path(getattr(settings, 'RAG_INDEX_DIR', 'rag_index'))
        out.mkdir(parents=True, exist_ok=True)

        docs, metas = harvest_docs(opts.get('topics'))
        self.stdout.write(self.style.NOTICE(f"Docs: {len(docs)}"))

        emb = make_embedder()
        X = emb.encode(docs)  # (N, d)

        (out / "docs.json").write_text(json.dumps(docs, ensure_ascii=False, indent=0), encoding="utf-8")
        (out / "metas.json").write_text(json.dumps(metas, ensure_ascii=False, indent=0), encoding="utf-8")
        np.save(out / "embeddings.npy", X.astype("float32"))

        self.stdout.write(self.style.SUCCESS(f"Saved to {out}"))
