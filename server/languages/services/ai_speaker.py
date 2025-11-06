import os
from typing import List
from languages.models import RoleplayBlock

USE_PARAPHRASE = bool(int(os.getenv("ROLEPLAY_PARAPHRASE_OTHER", "0")))

def _plain_lines(blocks: List[RoleplayBlock]):
    return [{"role": b.role or "-", "block_id": str(b.id), "text": b.text} for b in blocks]

def _paraphrase_lines(blocks: List[RoleplayBlock]):
    try:
        import google.generativeai as genai
        api = os.getenv("GEMINI_API_KEY")
        if not api: return _plain_lines(blocks)
        genai.configure(api_key=api)
        model = genai.GenerativeModel(os.getenv("GEMINI_MODEL","models/gemini-2.5-flash"),
                                      system_instruction="Paraphrase very concisely, preserve meaning, CEFR friendly.")
        lines = []
        for b in blocks:
            p = f"Paraphrase briefly and keep the intent. Original: {b.text}"
            out = (model.generate_content(p).text or "").strip()
            lines.append({"role": b.role or "-", "block_id": str(b.id), "text": out or b.text})
        return lines
    except Exception:
        return _plain_lines(blocks)

def ai_lines_for(blocks, learner_role: str):
    blocks = [b for b in blocks if (b.role or "") != learner_role]
    return [{"role": b.role or "-", "block_id": str(b.id), "text": b.text} for b in blocks]

