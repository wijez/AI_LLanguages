import base64
import hashlib
import os
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from speech.services import tts_synthesize


def generate_block_tts(block):
    """
    Sinh TTS cho RoleplayBlock.text và trả về audio_url
    """
    text = (block.text or "").strip()
    if not text:
        return ""

    lang = block.lang_hint or "en"
    voice = block.tts_voice or None

    # 1) synth
    audio_b64, mimetype = tts_synthesize(text, lang)

    raw = base64.b64decode(audio_b64)
    if len(raw) < 1000:
        raise RuntimeError("TTS output too small")

    # 2) filename theo hash (cache-friendly)
    h = hashlib.sha1(f"{lang}|{text}".encode("utf-8")).hexdigest()[:16]
    ext = ".mp3" 
    rel_path = f"tts/roleplay/{lang}/{h}{ext}"

    # 3) save file nếu chưa tồn tại
    if not default_storage.exists(rel_path):
        default_storage.save(rel_path, ContentFile(raw))

    # 4) build absolute URL
    return rel_path


def generate_tts_from_text(text: str, lang: str = "en", voice: str = None):
    """
    Sinh file audio tạm từ text raw (phục vụ AI dynamic response).
    """
    if not text: return ""
    
    # 1) Gọi service TTS (tái sử dụng tts_synthesize)
    try:
        audio_b64, mimetype = tts_synthesize(text, lang) 
        raw = base64.b64decode(audio_b64)
        
        # 2) Lưu file (dùng hash text làm tên file để cache nếu câu lặp lại)
        h = hashlib.sha1(f"dynamic|{lang}|{text}".encode("utf-8")).hexdigest()[:16]
        rel_path = f"tts/dynamic/{lang}/{h}.mp3"
        
        if not default_storage.exists(rel_path):
            default_storage.save(rel_path, ContentFile(raw))
            
        return rel_path 
    except Exception as e:
        print(f"[TTS Dynamic Error] {e}")
        return ""
