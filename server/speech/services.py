import base64
import os
import re
import tempfile
from functools import lru_cache

from gtts import gTTS
import whisper


# ------------------------- Helpers -------------------------

def _strip_data_url_prefix(b64: str) -> str:
    """
    Cho phép FE gửi 'data:audio/wav;base64,...'
    """
    if "," in b64 and b64.strip().lower().startswith("data:"):
        return b64.split(",", 1)[1]
    return b64


def _normalize_text(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-zA-Z0-9\u00C0-\u1EF9\s']", " ", s)  # giữ dấu tiếng Việt cơ bản
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _word_list(s: str):
    return [w for w in _normalize_text(s).split(" ") if w]


# ------------------------- TTS (gTTS) -------------------------

def tts_synthesize(text: str, lang: str | None = None) -> tuple[str, str]:
    """
    Sinh audio bằng gTTS → trả (audio_base64, mime_type).
    """
    lang = (lang or "en").lower()

    # gTTS sẽ raise nếu lang không hỗ trợ → fallback 'en'
    try:
        tts = gTTS(text=text, lang=lang)
    except Exception:
        tts = gTTS(text=text, lang="en")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name
        tts.save(tmp_path)

        with open(tmp_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode("utf-8")
        return audio_b64, "audio/mpeg"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


# ------------------------- STT (Whisper) -------------------------

@lru_cache(maxsize=1)
def _get_whisper_model():
    """
    Lazy-load Whisper 1 lần. Chọn 'small' cho chất lượng/hiệu năng cân bằng.
    Có thể đổi 'base'/'medium' tùy GPU/CPU.
    """
    # fp16=False để chạy tốt trên CPU/Windows
    return whisper.load_model("small")


def stt_transcribe(audio_base64: str, lang: str | None = None) -> str:
    """
    Giải base64 → file tạm → Whisper.transcribe() → text.
    """
    audio_base64 = _strip_data_url_prefix(audio_base64)

    tmp_path = None
    try:
        raw = base64.b64decode(audio_base64)
        # Đặt .wav để ffmpeg hiểu định dạng; nếu FE gửi webm/ogg vẫn OK nhờ ffmpeg.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(raw)
            tmp.flush()
            tmp_path = tmp.name

        model = _get_whisper_model()

        # language: code 2 chữ (vd 'en','vi'); None thì auto-detect
        # task='transcribe' để giữ nguyên ngôn ngữ; 'translate' nếu muốn dịch sang EN
        result = model.transcribe(tmp_path, language=(lang or None), task="transcribe", fp16=False)
        text = (result.get("text") or "").strip()
        return text
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


# ------------------------- Pron scoring (đơn giản) -------------------------

def simple_pron_score(expected: str, recognized: str) -> tuple[float, dict]:
    """
    Chấm điểm đơn giản dựa trên tỉ lệ từ khớp theo thứ tự (0..1).
    Bạn có thể thay bằng alignment theo phoneme sau này.
    """
    exp_words = _word_list(expected)
    rec_words = _word_list(recognized)

    if not exp_words:
        return 1.0, {"matched": 0, "total": 0}

    matched = 0
    i = 0
    for w in rec_words:
        if i < len(exp_words) and w == exp_words[i]:
            matched += 1
            i += 1

    score = matched / max(1, len(exp_words))
    details = {
        "matched": matched,
        "total": len(exp_words),
        "expected_norm": " ".join(exp_words),
        "recognized_norm": " ".join(rec_words),
        "method": "sequential-word-match"
    }
    return score, details
