import os, time, requests, logging
from typing import List


log = logging.getLogger(__name__)
BASE = os.getenv("RAG_OLLAMA_URL", "http://127.0.0.1:11435")
MODEL = os.getenv("RAG_OLLAMA_EMBED_MODEL", "nomic-embed-text:latest")
DIM = int(os.getenv("EMBED_DIM", "768"))

def _resize(vec: List[float]) -> List[float]:
    if len(vec) == DIM: return vec
    return (vec[:DIM]) if len(vec) > DIM else (vec + [0.0]*(DIM-len(vec)))

def embed_one(text: str, timeout=60, retries=2, backoff=0.6) -> List[float]:
    url = f"{BASE}/api/embeddings"
    payload = {"model": MODEL, "prompt": text}
    last = None
    for i in range(retries+1):
        try:
            r = requests.post(url, json=payload, timeout=timeout)
            r.raise_for_status()
            vec = r.json().get("embedding") or []
            return _resize(vec)
        except Exception as e:
            last = e
            time.sleep(backoff * (2**i))
    raise RuntimeError(f"Ollama embed failed: {last}")

def embed_many(texts: List[str], sleep_ms=20) -> List[List[float]]:
    out = []
    for t in texts:
        out.append(embed_one(t))
        if sleep_ms: time.sleep(sleep_ms/1000.0)
    return out
