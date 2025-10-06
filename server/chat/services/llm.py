# chat/services/llm.py
from typing import List, Dict, Optional
import os, httpx
from django.conf import settings
from languages.models import Language

OLLAMA_URL = os.getenv("OLLAMA_URL", getattr(settings, "RAG_OLLAMA_URL", "http://localhost:11435"))
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:latest")
REQUEST_TIMEOUT = 60.0

def build_system_prompt(topic: dict, mode: str, roleplay: dict) -> str:
    role = roleplay.get('role', 'trợ giảng')
    lang = topic.get('language', 'en')
    title = topic.get('title', 'Chung')
    return (
        f"Bạn là trợ giảng thân thiện. Chủ đề: {title}.\n"
        f"Chế độ: {mode}. Vai: {role}.\n"
        f"Ngôn ngữ: {lang}.\n"
        "Nguyên tắc: bám sát chủ đề, trả lời ngắn + hỏi lại, đề xuất 2–3 gợi ý."
    )

def _pack_messages(system: Optional[str], history: List[Dict[str, str]], user_text: str):
    msgs = []
    if system: msgs.append({"role":"system","content":system})
    for t in history:
        if t['role'] in ('user','assistant') and t['content'].strip():
            msgs.append({"role": t['role'], "content": t['content']})
    msgs.append({"role":"user","content":user_text})
    return msgs

def _fallback_suggestions(_reply: str):
    return ["Bạn muốn đi sâu phần nào tiếp?", "Bạn có ví dụ cụ thể không?", "Muốn luyện tập thêm không?"][:3]

async def call_llm(system, history, user_text, *, options=None, model=None):
    payload = {"model": model or OLLAMA_MODEL, "messages": _pack_messages(system, history, user_text), "stream": False}
    if options: payload["options"] = options
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        r = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        r.raise_for_status()
        data = r.json()
    reply = (data.get("message") or {}).get("content", "").strip()
    return {"text": reply, "meta": {"suggestions": _fallback_suggestions(reply), "confidence": 0.7}}
