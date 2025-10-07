from typing import List, Dict, Optional, Iterator, Any
import os, httpx, json, logging
from django.conf import settings
from ..models import Turn

log = logging.getLogger(__name__)

OLLAMA_URL   = os.getenv("OLLAMA_URL", getattr(settings, "RAG_OLLAMA_URL", "http://127.0.0.1:11435"))
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:latest")

DEFAULT_OPTIONS = {
    "temperature": 0.4,
    "top_p": 0.9,
    "repeat_penalty": 1.05,
    "num_ctx": 1536,
    "num_predict": 160,
    "stop": ["\nUser:", "\nuser:", "\nAssistant:", "\nassistant:"],
    "keep_alive": "15m",
}

# ---------------- clients ----------------
_async_client: httpx.AsyncClient | None = None
_sync_client:  httpx.Client      | None = None

def _get_sync_client() -> httpx.Client:
    global _sync_client
    if _sync_client is None:
        _sync_client = httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=None, write=30.0, pool=None),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            headers={"Connection": "keep-alive", "Accept": "application/x-ndjson"},
        )
    return _sync_client


def build_system_prompt(*, topic: Dict[str, Any], mode: str = "roleplay", roleplay: Dict[str, Any] | None = None) -> str:
    roleplay = roleplay or {}
    language = topic.get("language", "en")
    title = topic.get("title", "General Conversation")
    rp_role = roleplay.get("role") or "tutor"

    note = (
        f"You are a {rp_role} helping the learner practice '{title}'. "
        "Keep replies short (1–3 sentences) and ask a guiding follow-up."
    )

    guardrails = (
        "If the learner makes mistakes, correct them gently and provide a better phrasing. "
        "Prefer the conversation language unless explicitly asked to translate."
    )

    return (
        f"System Instruction (Language={language}):\n"
        f"{note}\n{guardrails}\n"
        "Format: plain text; avoid markdown lists unless asked."
    )


async def _get_async_client() -> httpx.AsyncClient:
    global _async_client
    if _async_client is None:
        _async_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=None),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            headers={"Connection": "keep-alive"},
        )
    return _async_client

# ---------------- helpers ----------------
def _pack_messages(system: str | None, history: list[dict], user_text: str):
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    for t in history:
        if t.get("role") in ("user", "assistant") and (t.get("content") or "").strip():
            msgs.append({"role": t["role"], "content": t["content"]})
    msgs.append({"role": "user", "content": user_text})
    return msgs

def _fallback_suggestions(_reply: str):
    return ["Bạn muốn đi sâu phần nào tiếp?", "Bạn có ví dụ cụ thể không?", "Muốn luyện tập thêm không?"][:3]

# ---------------- main calls ----------------
async def call_llm(system, history, user_text, *, options=None, model=None, stream=False):
    """Async non-stream call: dùng trong ChatViewSet.message (asyncio.run)."""
    merged_opts = {**DEFAULT_OPTIONS, **(options or {})}
    payload = {
        "model": model or OLLAMA_MODEL,
        "messages": _pack_messages(system, history, user_text),
        "stream": bool(stream),  # ở đây = False theo mặc định
        "options": merged_opts,
    }
    try:
        client = await _get_async_client()
        r = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        r.raise_for_status()
        data = r.json()
        reply = (data.get("message") or {}).get("content", "").strip()
        return {"text": reply, "meta": {"suggestions": _fallback_suggestions(reply), "confidence": 0.7}}
    except httpx.HTTPError as e:
        log.error("call_llm HTTPError: %s", e)
        # fallback trả câu đơn giản để FE không trống
        return {"text": "Xin lỗi, hiện không kết nối được mô hình. Mình sẽ trả lời ngắn gọn.", 
                "meta": {"suggestions": _fallback_suggestions(""), "confidence": 0.3}}

def stream_llm_sync(system, history, user_text, *, options=None, model=None) -> Iterator[bytes]:
    """
    Trả NDJSON sync cho StreamingHttpResponse:
      {"type":"start"}
      {"delta":"..."}*
      {"meta":{"suggestions":[...],"confidence":0.7}}
      {"type":"done"}
    Có fallback non-stream nếu stream fail (disconnected).
    """
    merged_opts = {**DEFAULT_OPTIONS, **(options or {})}
    payload = {
        "model": model or OLLAMA_MODEL,
        "messages": _pack_messages(system, history, user_text),
        "stream": True,
        "options": merged_opts,
    }
    client = _get_sync_client()
    parts: list[str] = []

    def line(obj: dict) -> bytes:
        return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")

    yield line({"type": "start"})

    try:
        with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload) as r:
            r.raise_for_status()
            for raw in r.iter_lines():
                if not raw:
                    continue
                try:
                    j = json.loads(raw)
                except Exception:
                    continue
                if j.get("done"):
                    break
                piece = (j.get("message") or {}).get("content") or ""
                if piece:
                    parts.append(piece)
                    yield line({"delta": piece})
    except httpx.HTTPError as e:
        # fallback non-stream (trong cùng request) để FE vẫn có câu trả lời
        try:
            p2 = dict(payload); p2["stream"] = False
            r2 = client.post(f"{OLLAMA_URL}/api/chat", json=p2)
            r2.raise_for_status()
            data = r2.json()
            text = (data.get("message") or {}).get("content") or ""
            if text:
                parts.append(text)
                yield line({"delta": text})
        except Exception as e2:
            yield line({"delta": f"(Stream error: {e}; fallback error: {e2})"})

    reply = "".join(parts).strip()
    yield line({"meta": {"suggestions": _fallback_suggestions(reply), "confidence": 0.7}})
    yield line({"type": "done"})
