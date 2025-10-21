# chat/rag/retriever.py
from __future__ import annotations
from typing import List, Dict, Iterable, Optional
import os, json
import numpy as np
from numpy.linalg import norm
from django.conf import settings

try:
    from .embedders import get_embedder
except Exception:
    get_embedder = None

def _index_dir() -> str:
    return getattr(settings, "RAG_INDEX_DIR", os.path.join(settings.BASE_DIR, "rag_index"))

class RagIndex:
    def __init__(self, dirpath: Optional[str] = None):
        self.dir = dirpath or _index_dir()
        self.docs: List[str] = []
        self.metas: List[Dict] = []
        self.embs: Optional[np.ndarray] = None
        self._loaded = False
        self._embedder = None

    def ensure(self):
        if self._loaded:
            return
        with open(os.path.join(self.dir, "docs.json"), "r", encoding="utf-8") as f:
            self.docs = json.load(f)
        with open(os.path.join(self.dir, "metas.json"), "r", encoding="utf-8") as f:
            self.metas = json.load(f)
        self.embs = np.load(os.path.join(self.dir, "embeddings.npy"))
        if get_embedder is None:
            raise RuntimeError("No embedding backend for query.")
        self._embedder = get_embedder()
        self._loaded = True

    def _cosine_topk(self, qvec: np.ndarray, k: int, mask: Optional[np.ndarray] = None):
        X = self.embs if mask is None else self.embs[mask]
        dots = X @ qvec
        sims = dots / (norm(X, axis=1) * (norm(qvec) + 1e-9) + 1e-9)
        idx = np.argpartition(-sims, min(k, len(sims)-1))[:k]
        order = idx[np.argsort(-sims[idx])]
        if mask is None:
            return order, sims[order]
        else:
            # map back to global indices
            global_idx = np.nonzero(mask)[0][order]
            return global_idx, sims[order]

    def _build_mask(self,
                    language: Optional[str] = None,
                    topic_slugs: Optional[Iterable[str]] = None,
                    lesson_ids: Optional[Iterable[int]] = None,
                    skill_ids: Optional[Iterable[int]] = None) -> Optional[np.ndarray]:
        if not any([language, topic_slugs, lesson_ids, skill_ids]):
            return None
        mask = np.ones(len(self.metas), dtype=bool)
        if language:
            mask &= np.array([m.get("language") == language for m in self.metas])
        if topic_slugs:
            ts = set(topic_slugs)
            mask &= np.array([m.get("topic_slug") in ts for m in self.metas])
        if lesson_ids:
            L = set(int(x) for x in lesson_ids)
            mask &= np.array([int(m.get("lesson_id", -1)) in L for m in self.metas])
        if skill_ids:
            S = set(int(x) for x in skill_ids)
            mask &= np.array([int(m.get("skill_id", -1)) in S for m in self.metas])
        return mask

    def search(self, query: str, top_k: int = 6, **filters) -> List[Dict]:
        self.ensure()
        qvec = self._embedder.embed_query(query).reshape(-1)
        mask = self._build_mask(
            language=filters.get("language"),
            topic_slugs=filters.get("topics"),
            lesson_ids=filters.get("lessons"),
            skill_ids=filters.get("skills"),
        )
        idx, sims = self._cosine_topk(qvec, top_k, mask=mask)
        out = []
        for i, score in zip(idx, sims):
            out.append({
                "text": self.docs[i],
                "score": float(score),
                "meta": self.metas[i],
            })
        return out

# Singleton tiện dụng
_INDEX: Optional[RagIndex] = None
def get_index() -> RagIndex:
    global _INDEX
    if _INDEX is None:
        _INDEX = RagIndex()
    return _INDEX
