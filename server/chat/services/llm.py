from typing import List, Dict, Optional, Iterator, Any, AsyncIterator
import os, httpx, json, logging
from django.conf import settings
from ..models import Turn

log = logging.getLogger(__name__)

OLLAMA_URL   = os.getenv("OLLAMA_URL", getattr(settings, "RAG_OLLAMA_URL", "http://127.0.0.1:11435"))
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:latest")

# Giữ default như cũ nhưng sẽ tách keep_alive/stop sang top-level khi gửi payload
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
            headers={
                "Connection": "keep-alive",
                "Accept": "application/x-ndjson",  # để server biết trả về dòng
            },
        )
    return _sync_client

async def _get_async_client() -> httpx.AsyncClient:
    global _async_client
    if _async_client is None:
        _async_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=None, write=30.0, pool=None),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            headers={
                "Connection": "keep-alive",
                "Accept": "application/x-ndjson",
            },
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

def _split_top_level_fields(options: Dict[str, Any] | None):
    """Tách keep_alive/stop ra khỏi options để đưa lên top-level payload."""
    opts = dict(options or {})
    keep_alive = opts.pop("keep_alive", None)
    stop = opts.pop("stop", None)
    # Tối ưu CPU: mặc định num_thread ~ n/2 nếu chưa set
    opts.setdefault("num_thread", max(2, (os.cpu_count() or 4) // 2))
    return opts, keep_alive, stop

def _ndjson_line(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")

# ---------------- main calls ----------------
async def call_llm(system, history, user_text, *, options=None, model=None, stream=False):
    """Async non-stream call: dùng trong ChatViewSet.message."""
    merged_opts = {**DEFAULT_OPTIONS, **(options or {})}
    opts, keep_alive, stops = _split_top_level_fields(merged_opts)

    payload = {
        "model": model or OLLAMA_MODEL,
        "messages": _pack_messages(system, history, user_text),
        "stream": bool(stream),  # ở đây thường False
        "options": opts,
    }
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
    if stops:
        payload["stop"] = stops

    try:
        client = await _get_async_client()
        r = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        r.raise_for_status()
        data = r.json()
        reply = (data.get("message") or {}).get("content", "").strip()
        return {"text": reply, "meta": {"suggestions": _fallback_suggestions(reply), "confidence": 0.7}}
    except httpx.HTTPError as e:
        log.error("call_llm HTTPError: %s", e)
        return {"text": "Xin lỗi, hiện không kết nối được mô hình. Mình sẽ trả lời ngắn gọn.",
                "meta": {"suggestions": _fallback_suggestions(""), "confidence": 0.3}}

def stream_llm_sync(system, history, user_text, *, options=None, model=None) -> Iterator[bytes]:
    """
    Stream NDJSON cho StreamingHttpResponse (sync):
      {"type":"start"}
      {"delta":"..."}*
      {"meta":{"suggestions":[...],"confidence":0.7}}
      {"type":"done"}
    """
    merged_opts = {**DEFAULT_OPTIONS, **(options or {})}
    opts, keep_alive, stops = _split_top_level_fields(merged_opts)

    payload = {
        "model": model or OLLAMA_MODEL,
        "messages": _pack_messages(system, history, user_text),
        "stream": True,
        "options": opts,
    }
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
    if stops:
        payload["stop"] = stops

    client = _get_sync_client()
    parts: list[str] = []

    yield _ndjson_line({"type": "start"})

    try:
        with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload) as r:
            r.raise_for_status()
            for raw in r.iter_lines():
                if not raw:
                    continue
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8", "ignore")
                try:
                    j = json.loads(raw)
                except Exception:
                    continue
                if j.get("done"):
                    break
                piece = (j.get("message") or {}).get("content") or ""
                if piece:
                    parts.append(piece)
                    yield _ndjson_line({"delta": piece})
    except httpx.HTTPError as e:
        # fallback non-stream để FE vẫn có kết quả
        try:
            p2 = dict(payload); p2["stream"] = False
            r2 = client.post(f"{OLLAMA_URL}/api/chat", json=p2)
            r2.raise_for_status()
            data = r2.json()
            text = (data.get("message") or {}).get("content") or ""
            if text:
                parts.append(text)
                yield _ndjson_line({"delta": text})
        except Exception as e2:
            yield _ndjson_line({"delta": f"(Stream error: {e}; fallback error: {e2})"})

    reply = "".join(parts).strip()
    yield _ndjson_line({"meta": {"suggestions": _fallback_suggestions(reply), "confidence": 0.7}})
    yield _ndjson_line({"type": "done"})

# ---------------- NEW: async generator stream ----------------
async def astream_llm(system, history, user_text, *, options=None, model=None) -> AsyncIterator[bytes]:
    """
    Async NDJSON stream (dùng cho async view/WebSocket/ASGI):
      {"type":"start"}
      {"delta":"..."}*
      {"meta":{...}}
      {"type":"done"}
    """
    merged_opts = {**DEFAULT_OPTIONS, **(options or {})}
    opts, keep_alive, stops = _split_top_level_fields(merged_opts)

    payload = {
        "model": model or OLLAMA_MODEL,
        "messages": _pack_messages(system, history, user_text),
        "stream": True,
        "options": opts,
    }
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
    if stops:
        payload["stop"] = stops

    client = await _get_async_client()
    parts: list[str] = []

    yield _ndjson_line({"type": "start"})

    try:
        async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload) as r:
            r.raise_for_status()
            async for raw in r.aiter_lines():
                if not raw:
                    continue
                # raw ở đây là str, nhưng decode phòng hờ:
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8", "ignore")
                try:
                    j = json.loads(raw)
                except Exception:
                    continue
                if j.get("done"):
                    break
                piece = (j.get("message") or {}).get("content") or ""
                if piece:
                    parts.append(piece)
                    yield _ndjson_line({"delta": piece})
    except httpx.HTTPError as e:
        # fallback non-stream (vẫn trong cùng response)
        try:
            p2 = dict(payload); p2["stream"] = False
            r2 = await client.post(f"{OLLAMA_URL}/api/chat", json=p2)
            r2.raise_for_status()
            data = r2.json()
            text = (data.get("message") or {}).get("content") or ""
            if text:
                parts.append(text)
                yield _ndjson_line({"delta": text})
        except Exception as e2:
            yield _ndjson_line({"delta": f"(Stream error: {e}; fallback error: {e2})"})

    reply = "".join(parts).strip()
    yield _ndjson_line({"meta": {"suggestions": _fallback_suggestions(reply), "confidence": 0.7}})
    yield _ndjson_line({"type": "done"})


def build_system_prompt(
    *, topic: Dict[str, Any], mode: str = "roleplay", roleplay: Optional[Dict[str, Any]] = None
) -> str:
    """
    Trả về system prompt cho LLM dựa theo topic/mode/roleplay.
    - topic: {"title": str, "language": "vi" | "en" | ...}
    - mode:  "roleplay" | "explain" | "quiz" | "free"
    - roleplay (tùy chọn): {"role": "tutor", "persona": "...", "scenario": "...", "level": "A1/B1/..."}

    Gợi ý: phần RAG (REFERENCE MATERIALS) sẽ được views bổ sung sau khi truy hồi ngữ cảnh.
    """
    roleplay = roleplay or {}

    language = (topic or {}).get("language") or "en"
    title = (topic or {}).get("title") or "General Conversation"

    rp_role = roleplay.get("role") or ("conversation partner" if mode == "roleplay" else "tutor")
    persona = roleplay.get("persona")
    scenario = roleplay.get("scenario")
    level = roleplay.get("level")  # ví dụ: "A1", "A2", "B1"...

    # Phần khung theo mode
    if mode == "roleplay":
        style = (
            f"You are a {rp_role} helping the learner practice '{title}'. "
            "Keep replies short (1–3 sentences) and ask exactly one guiding follow-up question."
        )
    elif mode == "explain":
        style = (
            f"You are a patient {rp_role} explaining '{title}'. "
            "Give clear, simple explanations and one short example. Keep answers under 5 sentences."
        )
    elif mode == "quiz":
        style = (
            f"You are a {rp_role} running a mini-quiz for '{title}'. "
            "Ask one question at a time and wait for the learner's answer before revealing solutions."
        )
    else:  # "free" hoặc mặc định
        style = f"You are a helpful {rp_role}."

    # Tuỳ biến thêm theo persona/scenario/level
    if persona:
        style += f" Stay in character as {persona}."
    if scenario:
        style += f" Scenario: {scenario}."
    if level:
        style += f" Adapt vocabulary and grammar to CEFR level {level}."

    guardrails = (
        "Use the conversation language unless explicitly asked to translate. "
        "If the learner makes mistakes, correct them gently and provide a better phrasing in one short line. "
        "Prefer plain text; avoid bullet lists unless asked. "
        "Be concise and concrete. If you are unsure, say you are unsure."
    )

    speaking_hint = (
        "When proposing speaking practice, suggest a short, natural target sentence the learner can read aloud."
    )

    # Ngôn ngữ hội thoại
    lang_line = f"Conversation language: {language}."

    # Gộp prompt cuối
    prompt = (
        f"{lang_line}\n"
        f"{style}\n"
        f"{guardrails}\n"
        f"{speaking_hint}"
    )
    return prompt