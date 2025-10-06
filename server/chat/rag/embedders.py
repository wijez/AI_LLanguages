# chat/rag/embedders.py
from typing import List
import numpy as np, httpx
from django.conf import settings

class SentenceTransformersEmbedder:
    def __init__(self, model_name=None):
        from sentence_transformers import SentenceTransformer
        self.m = SentenceTransformer(model_name or settings.RAG_ST_MODEL)
    def encode(self, texts: List[str]) -> np.ndarray:
        X = self.m.encode(texts, normalize_embeddings=True)
        return np.asarray(X, dtype="float32")

class OllamaEmbedder:
    def __init__(self, base_url=None, model=None, timeout=60.0):
        self.base = base_url or settings.RAG_OLLAMA_URL
        self.model = model or settings.RAG_OLLAMA_EMBED_MODEL
        self.timeout = timeout
    def encode(self, texts: List[str]) -> np.ndarray:
        vs = []
        with httpx.Client(timeout=self.timeout) as client:
            for t in texts:
                r = client.post(f"{self.base}/api/embeddings", json={"model": self.model, "prompt": t})
                r.raise_for_status()
                v = r.json().get("embedding", [])
                vs.append(v)
        X = np.asarray(vs, dtype="float32")
        X /= (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
        return X

def make_embedder():
    return SentenceTransformersEmbedder() if settings.RAG_EMBED_BACKEND == "st" else OllamaEmbedder()
