from __future__ import annotations

import json
from pathlib import Path
from typing import List, Tuple
import numpy as np
from django.conf import settings

from chat.rag.embedders import make_embedder


class Retriever:
    _singleton: "Retriever | None" = None

    def __init__(self, X: np.ndarray, metas: List[dict], docs: List[str], embedder):
        """
        X: (N, d) đã chuẩn hoá L2
        metas: list[dict] chứa {topic, skill, lesson, ...}
        docs:  list[str] văn bản
        embedder: backend encode truy vấn
        """
        self.X = X.astype("float32", copy=False)
        self.metas = metas
        self.docs = docs
        self.embedder = embedder
        self.XT = self.X.T  # tối ưu dot product

        self.N, self.D = self.X.shape

    @classmethod
    def ensure(cls) -> "Retriever":
        """Singleton: nạp index từ settings.RAG_INDEX_DIR"""
        if cls._singleton is None:
            idx_dir = Path(getattr(settings, "RAG_INDEX_DIR", "rag_index"))
            emb = np.load(idx_dir / "embeddings.npy")
            metas = json.loads((idx_dir / "metas.json").read_text(encoding="utf-8"))
            docs = json.loads((idx_dir / "docs.json").read_text(encoding="utf-8"))
            embedder = make_embedder()
            cls._singleton = cls(emb, metas, docs, embedder)
        return cls._singleton

    # ---------- utilities ----------
    def embed(self, text: str) -> np.ndarray:
        """Mã hoá 1 câu truy vấn thành vector (d,) đã chuẩn hoá"""
        X = self.embedder.encode([text])
        if X.ndim == 2:
            x = X[0]
        else:
            x = X
        # an toàn nếu backend không chuẩn hoá
        n = np.linalg.norm(x) + 1e-9
        return (x / n).astype("float32", copy=False)

    # ---------- core search ----------
    def _mmr(
        self,
        qv_vec: np.ndarray,
        Xcand: np.ndarray,
        cand_idx: List[int],
        top_k: int,
        lam: float = 0.6,
    ) -> List[int]:
        """
        Maximal Marginal Relevance để đa dạng hoá kết quả.
        qv_vec: (d,), Xcand: (M, d), cand_idx: index trong Xcand
        return: danh sách index (theo Xcand) đã chọn
        """
        sel: List[int] = []
        C = cand_idx[:]
        while C and len(sel) < top_k:
            s_q = Xcand[C] @ qv_vec  # (|C|,)
            if not sel:
                i = int(np.argmax(s_q))
            else:
                s_div = np.max(Xcand[C] @ Xcand[sel].T, axis=1)  # độ giống các mục đã chọn
                mmr = lam * s_q - (1.0 - lam) * s_div
                i = int(np.argmax(mmr))
            sel.append(C[i])
            del C[i]
        return sel

    def search(
        self,
        query: str,
        topic: str | None = None,
        skill: str | None = None,
        k: int = 5,
    ) -> List[Tuple[float, dict, str]]:
        """
        Trả về list (score, meta, doc).
        Dot product trên vector chuẩn hoá ≈ cosine similarity.
        """
        qv = self.embed(query).reshape(1, -1)  # (1, d)
        TH = float(getattr(settings, "RAG_SCORE_THRESH", 0.25))

        # Lọc theo topic/skill
        mask = np.ones(self.N, dtype=bool)
        if topic:
            mask &= np.array([m.get("topic") == topic for m in self.metas], dtype=bool)
        if skill:
            mask &= np.array([m.get("skill") == skill for m in self.metas], dtype=bool)

        idxs = np.where(mask)[0]

        # Không có filter phù hợp → fall back toàn bộ
        if idxs.size == 0:
            sims_all = (qv @ self.XT)[0]  # (N,)
            wide = np.argpartition(-sims_all, min(3 * k, sims_all.size - 1))[: 3 * k]
            wide = [int(i) for i in wide if float(sims_all[int(i)]) >= TH]

            if not wide:
                top = sims_all.argsort()[::-1][:k]
                return [(float(sims_all[i]), self.metas[i], self.docs[i]) for i in top]

            chosen = self._mmr(qv[0], self.X, wide, k, lam=0.6)
            return [(float(sims_all[i]), self.metas[i], self.docs[i]) for i in chosen]

        # Có filter → tính trên tập con
        Xsub = self.X[idxs]
        sims = (qv @ Xsub.T)[0]  # (|idxs|,)

        wide = np.argpartition(-sims, min(3 * k, sims.size - 1))[: 3 * k]
        wide = [int(i) for i in wide if float(sims[int(i)]) >= TH]

        if not wide:
            top = sims.argsort()[::-1][:k]
            return [(float(sims[i]), self.metas[idxs[i]], self.docs[idxs[i]]) for i in top]

        chosen_local = self._mmr(qv[0], Xsub, wide, k, lam=0.6)
        return [(float(sims[i]), self.metas[idxs[i]], self.docs[idxs[i]]) for i in chosen_local]


def format_rag_snippet(hits: List[Tuple[float, dict, str]]) -> str:
    # Gói gọn tài liệu để nhúng vào system prompt
    return "\n".join(
        f"- ({m['topic']} / {m['skill']} / {m['lesson']}) :: {d}"
        for s, m, d in hits[:5]
    )
