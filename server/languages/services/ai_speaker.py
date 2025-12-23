import os, logging
from typing import List
from languages.models import RoleplayBlock
log = logging.getLogger(__name__)

USE_PARAPHRASE = bool(int(os.getenv("ROLEPLAY_PARAPHRASE_OTHER", "0")))

def _plain_lines(blocks: List[RoleplayBlock]):
    return [
        {
            "role": b.role or "-",
            "block_id": str(b.id),
            "text": b.text,
            "audio_key": b.audio_key,
        }
        for b in blocks
    ]

def _paraphrase_lines(blocks: List[RoleplayBlock]):
    try:
        import google.generativeai as genai
        api = os.getenv("GEMINI_API_KEY")
        if not api: 
            return _plain_lines(blocks)
        genai.configure(api_key=api)
        model = genai.GenerativeModel(os.getenv("GEMINI_MODEL","models/gemini-2.5-flash"),
                                      system_instruction="Paraphrase very concisely, preserve meaning, CEFR friendly.")
        lines = []
        for b in blocks:
            if len(b.text.split()) < 3:
                lines.append({
                    "role": b.role or "-",
                    "block_id": str(b.id),
                    "text": b.text,
                    "audio_key": b.audio_key,
                })
                continue
            p = f"Paraphrase briefly and keep the intent. Original: {b.text}"
            try:
                out = (model.generate_content(p).text or "").strip()
                lines.append({
                    "role": b.role or "-",
                    "block_id": str(b.id),
                    "text": out or b.text,
                    "audio_key": b.audio_key,
                })
            except Exception as e:
                log.error(f"Paraphrasing failed for block {b.id}: {e}")
                lines.append({
                    "role": b.role or "-",
                    "block_id": str(b.id),
                    "text": b.text,
                    "audio_key": b.audio_key,
                }) # Fallback
        return lines
    except Exception:
        return _plain_lines(blocks)

def ai_lines_for(blocks, learner_role: str):
    blocks = [b for b in blocks if (b.role or "") != learner_role]
    if USE_PARAPHRASE:
        return _paraphrase_lines(blocks)
    else:
        return _plain_lines(blocks)

