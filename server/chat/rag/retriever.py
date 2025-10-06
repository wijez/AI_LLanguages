# chat/rag/retriever.py
import json
from pathlib import Path
import numpy as np
from django.conf import settings
from chat.rag.embedders import make_embedder

class Retriever:
    _singleton = None
    def __init__(self, X, metas, docs, embedder):
        self.X = X; self.metas = metas; self.docs = docs; self.embedder = embedder
        self.XT = self.X.T  # tối ưu dot

    @classmethod
    def ensure(cls):
        if cls._singleton is None:
            base = Path(settings.RAG_INDEX_DIR)
            X = np.load(base / "embeddings.npy")
            metas = json.loads((base / "metas.json").read_text(encoding="utf-8"))
            docs  = json.loads((base / "docs.json").read_text(encoding="utf-8"))
            emb = make_embedder()
            cls._singleton = Retriever(X, metas, docs, emb)
        return cls._singleton

    def search(self, query: str, *, topic=None, skill=None, k=None):
        k = k or getattr(settings, "RAG_TOP_K", 5)
        qv = self.embedder.encode([query])  # (1,d)
        # mask
        mask = np.ones(len(self.docs), dtype=bool)
        if topic: mask &= np.array([m["topic"]==topic for m in self.metas])
        if skill: mask &= np.array([m["skill"]==skill for m in self.metas])
        idxs = np.where(mask)[0]
        if len(idxs)==0:
            sims = (qv @ self.XT)[0]
            top = sims.argsort()[::-1][:k]
            return [(float(sims[i]), self.metas[i], self.docs[i]) for i in top]
        Xsub = self.X[idxs]; XTsub = Xsub.T
        sims = (qv @ XTsub)[0]
        top = sims.argsort()[::-1][:k]
        return [(float(sims[i]), self.metas[idxs[i]], self.docs[idxs[i]]) for i in top]

def format_rag_snippet(hits):
    return "\n".join(f"- ({m['topic']} / {m['skill']} / {m['lesson']}) :: {d}" for s,m,d in hits[:5])
