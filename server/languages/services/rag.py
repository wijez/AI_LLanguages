import os
from typing import Optional
from django.db.models import F
from pgvector.django import CosineDistance
from languages.models import RoleplayBlock
from .ollama_client import embed_one
import google.generativeai as genai

def retrieve_blocks(q_text: str, top_k=88, scenario_slug: Optional[str] = None):
    q_vec = embed_one(q_text)
    qs = RoleplayBlock.objects.exclude(embedding__isnull=True)
    if scenario_slug: qs = qs.filter(scenario__slug=scenario_slug)
    return (qs.annotate(score=CosineDistance("embedding", q_vec))
             .order_by("score")[:top_k])


GEMINI_MODEL = os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash")
if os.getenv("GEMINI_API_KEY"): genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

SYS = ("You are a concise English tutor. Use the provided DIALOGUE CONTEXT. "
       "Keep responses short, encouraging, and on-topic.")

def ask_gemini(query: str, blocks) -> str:
    if not os.getenv("GEMINI_API_KEY"): return ""
    ctx = "\n".join([f"[{b.section}#{b.order}] {b.role or '-'}: {b.text}" for b in blocks])
    prompt = f"DIALOGUE CONTEXT:\n{ctx}\n\nUSER: {query}"
    m = genai.GenerativeModel(GEMINI_MODEL, system_instruction=SYS)
    return (m.generate_content(prompt).text or "").strip()
