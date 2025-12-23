import base64
import os
import re
import json
import subprocess
import tempfile
import urllib.parse
from typing import Tuple, Dict, Any, Optional

import numpy as np
from gtts import gTTS
from jiwer import wer, cer
import whisper
from difflib import SequenceMatcher
import shutil
from django.conf import settings
import logging
logger = logging.getLogger(__name__)

# =========================
# Debug switch
# =========================
DEBUG_AUDIO = True  # bật để in log & trả thông tin debug

# =========================
# Whisper model (lazy)
# =========================
_model = None
def get_model():
    global _model
    if _model is None:
        # chọn size phù hợp phần cứng: base/small/medium/large
        _model = whisper.load_model("small")
    return _model

# ở đầu file (thêm import)
import unicodedata
from pathlib import Path

def _sanitize_for_piper(text: str) -> str:
    """Loại surrogate/emoji/ZWJ và normalize để piper/espeak không lỗi."""
    if not isinstance(text, str):
        text = str(text)
    # bỏ surrogate range (U+D800..U+DFFF)
    text = re.sub(r'[\ud800-\udfff]', '', text)
    # bỏ ZWJ & variation selectors (hay gây lỗi với espeak)
    text = re.sub(r'[\u200d\ufe0e\ufe0f]', '', text)
    # chuẩn hóa Unicode
    try:
        text = unicodedata.normalize("NFC", text)
    except Exception:
        pass
    # loại control chars không in được (giữ lại khoảng trắng / newline / tab)
    text = ''.join(ch if ch.isprintable() or ch in '\n\r\t ' else ' ' for ch in text)
    # gọn khoảng trắng
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def _tts_piper_to_mp3_b64(text: str, lang: str) -> str:
    bin_path, voice_dir, voices = _piper_conf()

    if not shutil.which(bin_path):
        raise RuntimeError("piper_not_found")

    lang = (lang or "en").lower().strip()
    voice_file = voices.get(lang) or voices.get("en")
    if not voice_file:
        raise RuntimeError("piper_voice_not_configured")

    model_path = voice_file if os.path.isabs(voice_file) else os.path.join(voice_dir, voice_file)
    if not os.path.exists(model_path):
        raise RuntimeError(f"piper_voice_missing:{model_path}")

    # tìm file config .json đi kèm
    cands = [
        model_path + ".json",
        model_path.replace(".onnx", ".onnx.json"),
        model_path.replace(".onnx", ".json"),
    ]
    config_path = next((p for p in cands if os.path.exists(p)), None)
    if not config_path:
        raise RuntimeError(f"piper_config_missing:{model_path}.json")

    # env “an toàn” cho Windows temp
    tmp_dir = Path(getattr(settings, "PIPER_TMP_DIR", Path(getattr(settings, "BASE_DIR", Path.cwd())) / "tmp")).resolve()
    tmp_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "TMP": str(tmp_dir),
        "TEMP": str(tmp_dir),
        "TMPDIR": str(tmp_dir),
        "PYTHONIOENCODING": "utf-8",
    })

    clean = _sanitize_for_piper(text)

    # 1) thử stdout
    try:
        p = subprocess.run(
            [bin_path, "--model", model_path, "--config", config_path, "--output_file", "-"],
            input=clean.encode("utf-8", "ignore"),
            capture_output=True,
            check=True,
            env=env,
        )
        wav_bytes = p.stdout
        if not wav_bytes:
            raise RuntimeError("piper_no_audio_stdout")
        return _wav_bytes_to_mp3_b64(wav_bytes)
    except Exception as e1:
        # 2) thử ghi file tạm
        tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        try:
            p2 = subprocess.run(
                [bin_path, "--model", model_path, "--config", config_path, "--output_file", tmp_wav],
                input=clean.encode("utf-8", "ignore"),
                capture_output=True,
                check=True,
                env=env,
            )
            if not os.path.exists(tmp_wav) or os.path.getsize(tmp_wav) == 0:
                raise RuntimeError(f"piper_no_audio_file rc={p2.returncode} stderr={p2.stderr.decode(errors='ignore')}")
            with open(tmp_wav, "rb") as f:
                wav_bytes = f.read()
            return _wav_bytes_to_mp3_b64(wav_bytes)
        finally:
            _safe_remove(tmp_wav)


def _piper_conf():
    """
    Lấy cấu hình Piper từ settings hoặc ENV:
      - PIPER_BIN: đường dẫn 'piper' (vd 'piper' hoặc 'C:\\tools\\piper.exe')
      - PIPER_VOICE_DIR: thư mục chứa các model .onnx
      - PIPER_VOICES: map ngôn ngữ -> tên file model (tương đối so với VOICE_DIR hoặc path tuyệt đối)
    """
    bin_path = getattr(settings, "PIPER_BIN", os.environ.get("PIPER_BIN", "piper"))
    voice_dir = getattr(settings, "PIPER_VOICE_DIR", os.environ.get("PIPER_VOICE_DIR", os.path.join(os.getcwd(), "voices")))
    voices = getattr(settings, "PIPER_VOICES", None)
    if not voices:
        voices = {
            "en": "en_US-amy-medium.onnx",
            "vi": "vi_VN-25hours_single-low.onnx",
            "zh": "zh_CN-huayan-medium.onnx",
        }
    return bin_path, voice_dir, voices

def _wav_bytes_to_mp3_b64(wav_bytes: bytes) -> str:
    """
    Dùng ffmpeg để convert WAV bytes -> MP3 (base64 không kèm prefix data:).
    Cần có ffmpeg trong PATH.
    """
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-f", "mp3", "pipe:1"],
        input=wav_bytes, capture_output=True, check=True
    )
    return base64.b64encode(p.stdout).decode("utf-8")

# def _tts_piper_to_mp3_b64(text: str, lang: str) -> str:
#     """
#     Sinh giọng bằng Piper và trả MP3 base64. Ném Exception nếu thiếu piper/voice/ffmpeg.
#     """
#     bin_path, voice_dir, voices = _piper_conf()

#     # 1) phải có piper
#     if not shutil.which(bin_path):
#         raise RuntimeError("piper_not_found")

#     # 2) lấy model theo lang (fallback 'en')
#     lang = (lang or "en").lower().strip()
#     voice_file = voices.get(lang) or voices.get("en")
#     if not voice_file:
#         raise RuntimeError("piper_voice_not_configured")

#     model_path = voice_file if os.path.isabs(voice_file) else os.path.join(voice_dir, voice_file)
#     if not os.path.exists(model_path):
#         raise RuntimeError(f"piper_voice_missing:{model_path}")

#     # 3) Gọi Piper đúng cờ: --model / --output_file
#     #    Thử xuất WAV ra stdout trước ( --output_file - ), nếu fail thì dùng file tạm.
#     try:
#         p = subprocess.run(
#             [bin_path, "--model", model_path, "--output_file", "-"],
#             input=text.encode("utf-8"),
#             capture_output=True,
#             check=True
#         )
#         wav_bytes = p.stdout
#         if not wav_bytes:
#             raise RuntimeError("piper_no_audio_stdout")
#         return _wav_bytes_to_mp3_b64(wav_bytes)
#     except Exception as e1:
#         # Thử lại với file WAV tạm (một số build Piper trên Windows ổn định hơn khi ghi file)
#         tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
#         try:
#             p2 = subprocess.run(
#                 [bin_path, "--model", model_path, "--output_file", tmp_wav],
#                 input=text.encode("utf-8"),
#                 capture_output=True,
#                 check=True
#             )
#             if not os.path.exists(tmp_wav) or os.path.getsize(tmp_wav) == 0:
#                 raise RuntimeError(f"piper_no_audio_file rc={p2.returncode} stderr={p2.stderr.decode(errors='ignore')}")
#             with open(tmp_wav, "rb") as f:
#                 wav_bytes = f.read()
#             return _wav_bytes_to_mp3_b64(wav_bytes)
#         except Exception as e2:
#             # Gộp lỗi cho dễ debug ở log phía trên
#             raise RuntimeError(f"piper_run_failed: stdout_err={getattr(e1,'stderr',b'')!r} file_err={getattr(e2,'stderr',b'')!r}") 
#         finally:
#             _safe_remove(tmp_wav)

# =========================
# Alignment helpers (NEW)
# =========================
def _lev_distance(a: str, b: str) -> int:
    import numpy as np
    dp = np.zeros((len(a)+1, len(b)+1), dtype=int)
    for i in range(len(a)+1): dp[i,0] = i
    for j in range(len(b)+1): dp[0,j] = j
    for i in range(1, len(a)+1):
        for j in range(1, len(b)+1):
            cost = 0 if a[i-1] == b[j-1] else 1
            dp[i,j] = min(dp[i-1,j] + 1, dp[i,j-1] + 1, dp[i-1,j-1] + cost)
    return int(dp[len(a), len(b)])

def _align_ref_hyp(ref_words: list[str], hyp_words_timed: list[dict], near_ok_ed: int = 1):
    """
    Trả:
      per_word: list[{word, score, start, end, status}]
      aligned_hyp_for_wer: list[str]  # bỏ các 'insert' để WER/CER chỉ tính phần expected
    """
    hyp_words = [w["word"] for w in hyp_words_timed]
    sm = SequenceMatcher(None, ref_words, hyp_words, autojunk=False)
    per_word = []
    aligned_hyp_for_wer = []

    def span_time(hs: int, he: int):
        if hs > he: hs, he = he, hs
        hs = max(0, hs); he = min(len(hyp_words_timed)-1, he)
        if hs <= he and len(hyp_words_timed) > 0:
            s = hyp_words_timed[hs].get("start")
            e = hyp_words_timed[he].get("end")
            return s, e
        return None, None

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                rw = ref_words[i1 + k]
                hw = hyp_words_timed[j1 + k]
                aligned_hyp_for_wer.append(hw["word"])
                ws = int(100 * 0.9)  # equal → mạnh tay 90
                status = "ok" if ws >= 80 else "practice"
                per_word.append({
                    "word": rw, "score": ws,
                    "start": hw.get("start"), "end": hw.get("end"),
                    "status": status
                })
        elif tag == "replace":
            L = min(i2 - i1, j2 - j1)
            for k in range(L):
                rw = ref_words[i1 + k]
                hw = hyp_words_timed[j1 + k]
                aligned_hyp_for_wer.append(hw["word"])
                near = (_lev_distance(rw.lower(), hw["word"].lower()) <= near_ok_ed)
                base = 0.8 if near else 0.55
                ws = int(100 * base)
                per_word.append({
                    "word": rw, "score": max(0, min(100, ws)),
                    "start": hw.get("start"), "end": hw.get("end"),
                    "status": "ok" if near and ws >= 80 else ("practice" if ws >= 60 else "mispronounced")
                })
            for k in range(L, i2 - i1):  # ref dư → missing
                rw = ref_words[i1 + k]
                per_word.append({"word": rw, "score": 40, "start": None, "end": None, "status": "missing"})
            # hyp dư (insert) → bỏ
        elif tag == "delete":
            for k in range(i2 - i1):
                rw = ref_words[i1 + k]
                per_word.append({"word": rw, "score": 40, "start": None, "end": None, "status": "missing"})
        elif tag == "insert":
            continue

    return per_word, aligned_hyp_for_wer

# =========================
# Prosody helper
# =========================
def _speed_factor(duration_s: float, num_chars: int) -> float:
    """
    Hệ số prosody dựa trên tốc độ nói xấp xỉ (syllables/sec).
    """
    if duration_s is None or duration_s <= 0:
        return 1.0
    syll_est = max(1.0, float(num_chars) / 3.0)
    rate = syll_est / max(0.1, float(duration_s))  # syll/sec
    target = 3.5  # tốc độ mục tiêu (EN)
    diff = abs(rate - target)
    if diff < 1.0:
        return 1.05
    if diff < 2.0:
        return 1.00
    return 0.90

# =========================
# ffprobe / ffmpeg helpers
# =========================
def _ffprobe_json(path: str) -> dict:
    try:
        out = subprocess.check_output([
            "ffprobe", "-hide_banner", "-loglevel", "error",
            "-print_format", "json", "-show_format", "-show_streams", path
        ])
        return json.loads(out.decode("utf-8"))
    except Exception:
        return {}

def _probe_duration_sec(probe: dict) -> Optional[float]:
    d = None
    try:
        if "format" in probe and "duration" in probe["format"]:
            d = float(probe["format"]["duration"])
    except Exception:
        d = None
    if d is None:
        try:
            for s in probe.get("streams", []):
                if s.get("codec_type") == "audio" and "duration" in s:
                    d = float(s["duration"])
                    break
        except Exception:
            d = None
    return d

def _ffmpeg_run(args: list) -> tuple[int, str, str]:
    """Chạy ffmpeg, trả (returncode, stdout, stderr)"""
    proc = subprocess.run(args, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr

def _ffmpeg_to_wav_16k_mono(src_path: str, trim_silence: bool = False) -> tuple[str, dict]:
    """
    Convert input -> WAV 16k mono.
    Mặc định KHÔNG cắt im lặng, KHÔNG bỏ frame hỏng.
    Nếu output ngắn bất thường so với input -> thử lại với các cấu hình khác.
    """
    info: dict = {
        "pass": "p1_plain",
        "rc": None,
        "stderr": "",
        "probe_in": {},
        "probe_out": {},
        "short_output_detected": False,
    }

    probe_in = _ffprobe_json(src_path)
    info["probe_in"] = probe_in
    in_dur = _probe_duration_sec(probe_in) or 0.0

    def _run(cmd):
        rc, so, se = _ffmpeg_run(cmd)
        return rc, (se or "")

    dst = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name

    # Pass 1: chuyển thẳng, KHÔNG discardcorrupt/ignore_err, KHÔNG silenceremove
    base1 = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-y",
        "-i", src_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        dst
    ]
    rc, se = _run(base1)
    info["rc"] = rc
    info["stderr"] = se

    def _probe_out_and_check(label):
        info["pass"] = label
        probe_out = _ffprobe_json(dst)
        info["probe_out"] = probe_out
        out_dur = _probe_duration_sec(probe_out) or 0.0
        # nếu đầu vào hợp lệ (>0.5s) mà đầu ra < 70% đầu vào thì coi là ngắn bất thường
        short = (in_dur >= 0.5 and out_dur < 0.7 * in_dur)
        info["short_output_detected"] = bool(short)
        return out_dur, short

    if rc == 0:
        out_dur, short = _probe_out_and_check("p1_plain")
        if not short:
            return dst, info
        # Nếu ngắn bất thường -> thử pass 2
        # (không xóa dst vội; sẽ ghi đè)
    else:
        # Ghi chú lỗi và thử pass 2
        pass

    # Pass 2: cho phép bỏ frame hỏng (đôi khi giúp kéo dài hơn)
    base2 = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-y",
        "-fflags", "+discardcorrupt",
        "-err_detect", "ignore_err",
        "-i", src_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        dst
    ]
    rc2, se2 = _run(base2)
    info["rc"] = rc2
    info["stderr"] += ("\n" + se2)
    if rc2 == 0:
        out_dur, short = _probe_out_and_check("p2_discardcorrupt")
        if not short:
            return dst, info

    # Pass 3: ép demuxer mp3 (sửa vụ “Header missing” / MPEG-2.5)
    base3 = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-y",
        "-f", "mp3",            # ép mp3 demuxer
        "-i", src_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        dst
    ]
    rc3, se3 = _run(base3)
    info["rc"] = rc3
    info["stderr"] += ("\n" + se3)
    if rc3 == 0:
        out_dur, short = _probe_out_and_check("p3_force_mp3")
        if not short:
            return dst, info

    # Pass 4 (tùy chọn): chỉ khi bạn MUỐN cắt im lặng, thử rất nhẹ 150ms @ -35dB
    if trim_silence:
        base4 = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-y",
            "-i", src_path,
            "-vn",
            "-af", "silenceremove=start_periods=1:start_silence=0.15:start_threshold=-35dB:stop_periods=1:stop_silence=0.15:stop_threshold=-35dB",
            "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            dst
        ]
        rc4, se4 = _run(base4)
        info["rc"] = rc4
        info["stderr"] += ("\n" + se4)
        if rc4 == 0:
            out_dur, short = _probe_out_and_check("p4_trim_silence")
            # dù “short” vẫn trả về để còn debug; caller sẽ thấy cờ short_output_detected

            return dst, info

    # Nếu đến đây vẫn lỗi, ném exception
    try:
        os.remove(dst)
    except OSError:
        pass
    raise RuntimeError("ffmpeg failed to decode audio (all passes)")

# =========================
# Text helpers
# =========================
def _normalize_text(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-zA-Z0-9\u00C0-\u1EF9\s']", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()

# =========================
# Base64 helpers (an toàn)
# =========================
def _strip_data_url_prefix(b64: str) -> str:
    if isinstance(b64, str) and b64.strip().lower().startswith("data:") and "," in b64:
        return b64.split(",", 1)[1]
    return b64

def _b64_to_bytes_any(s: str) -> bytes:
    """
    Giải base64 'bất chấp':
    - Hỗ trợ Data URL, khoảng trắng/newline, thiếu padding, urlsafe (-/_)
    - CHỈ unquote nếu thực sự có escape %XX (URL-encoded). KHÔNG dùng unquote_plus.
    """
    if not isinstance(s, str):
        raise ValueError("audio_base64 must be a string")

    # 1) Bỏ tiền tố data:...;base64,
    s = _strip_data_url_prefix(s).strip()

    # 2) Chỉ unquote nếu có chuỗi %hh (URL-encoded). Không dùng unquote_plus vì sẽ
    #    biến '+' thành ' ' (sai với base64).
    if re.search(r"%[0-9A-Fa-f]{2}", s):
        s = urllib.parse.unquote(s)

    # 3) Loại bỏ whitespace (không đụng tới '+', '-', '_', '=')
    s = re.sub(r"\s+", "", s)

    def _try_decode(t: str) -> bytes:
        missing = (-len(t)) % 4
        if missing:
            t += "=" * missing
        return base64.b64decode(t, validate=False)

    # 4) Base64 chuẩn
    try:
        return _try_decode(s)
    except Exception:
        pass

    # 5) urlsafe
    try:
        return _try_decode(s.replace("-", "+").replace("_", "/"))
    except Exception:
        pass

    # 6) lọc kí tự lạ (cứu vãn)
    t = re.sub(r"[^A-Za-z0-9+/=]", "", s)
    return _try_decode(t)

# =========================
# Bytes ↔ temp file helpers
# =========================
def _guess_audio_suffix(raw: bytes) -> str:
    if not raw or len(raw) < 12:
        return ".tmp"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WAVE": return ".wav"
    if raw[:3] == b"ID3" or (raw[0] == 0xFF and (raw[1] & 0xE0) == 0xE0): return ".mp3"
    if raw[:4] == b"OggS": return ".ogg"
    if raw[:4] == b"fLaC": return ".flac"
    if raw[:4] == b"\x1A\x45\xDF\xA3": return ".webm"
    if raw[4:8] == b"ftyp": return ".m4a"
    return ".tmp"

def _looks_like_audio(raw: bytes) -> bool:
    return bool(raw) and len(raw) >= 256 and _guess_audio_suffix(raw) != ".tmp"

def _bytes_to_temp_audio(raw: bytes, forced_suffix: Optional[str] = None) -> str:
    suffix = forced_suffix or _guess_audio_suffix(raw)
    f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        f.write(raw)
        f.flush()
        return f.name
    finally:
        f.close()

def _safe_remove(path: Optional[str]):
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass

def _debug_head(raw: bytes, label: str = "audio"):
    if not DEBUG_AUDIO: return
    try:
        print(f"[DEBUG] {label}: size={len(raw)} head16={raw[:16].hex()} suffix={_guess_audio_suffix(raw)}")
    except Exception:
        pass

# =========================
# TTS (gTTS)
# =========================
# def tts_synthesize(text: str, lang: Optional[str] = None) -> Tuple[str, str]:
#     lang = (lang or "en").lower()
#     try:
#         tts = gTTS(text=text, lang=lang)
#     except Exception:
#         tts = gTTS(text=text, lang="en")
#     tmp_path = None
#     try:
#         with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
#             tmp_path = tmp.name
#         tts.save(tmp_path)
#         with open(tmp_path, "rb") as f:
#             audio_b64 = base64.b64encode(f.read()).decode("utf-8")
#         return audio_b64, "audio/mpeg"
#     finally:
#         _safe_remove(tmp_path)

def tts_synthesize(text: str, lang: Optional[str] = None) -> Tuple[str, str]:
    """
    ƯU TIÊN Piper, gTTS chỉ để fallback.
    Nếu settings.PIPER_STRICT = True → Piper lỗi sẽ raise luôn, KHÔNG fallback.
    """
    lang_norm = (lang or "en").lower().strip()
    STRICT_PIPER = getattr(settings, "PIPER_STRICT", False)

    # ---- 1) Thử Piper trước ----
    try:
        b64 = _tts_piper_to_mp3_b64(text, lang_norm)
        logger.info("[TTS] Piper OK (lang=%s)", lang_norm)
        return b64, "audio/mpeg"
    except Exception as e:
        # Ghi log + quyết định có cho fallback hay không
        logger.warning("[TTS] Piper FAILED (lang=%s): %r", lang_norm, e)
        if STRICT_PIPER:
            # Muốn debug Piper, đặt PIPER_STRICT=True trong settings -> thấy lỗi ngay trên API
            raise

    # ---- 2) Fallback gTTS (khi Piper không chạy được) ----
    lang_fallback = lang_norm or "en"
    try:
        tts = gTTS(text=text, lang=lang_fallback)
        logger.info("[TTS] Using gTTS(lang=%s) as fallback", lang_fallback)
    except Exception:
        # Lang không hỗ trợ -> fallback EN
        tts = gTTS(text=text, lang="en")
        logger.info("[TTS] Using gTTS(lang=en) after lang=%s failed", lang_fallback)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name
        tts.save(tmp_path)
        with open(tmp_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode("utf-8")
        return audio_b64, "audio/mpeg"
    finally:
        _safe_remove(tmp_path)


# =========================
# STT (base64 → text)
# =========================
def stt_transcribe(audio_base64: str, lang: Optional[str] = None) -> str:
    text, _debug = stt_transcribe_with_debug(audio_base64, lang)
    return text

def stt_transcribe_with_debug(audio_base64: str, lang: Optional[str] = None) -> tuple[str, dict]:
    """
    Trả (text, debug_dict)
    """
    in_path, wav_path = None, None
    dbg = {"upload": {}, "ffmpeg": {}, "probe": {}}
    try:
        raw = _b64_to_bytes_any(audio_base64)
        _debug_head(raw, "stt")
        if not _looks_like_audio(raw):
            raise ValueError("Provided audio does not look like a valid audio file.")
        # upload debug
        dbg["upload"] = {
            "bytes_len": len(raw),
            "head16": raw[:16].hex(),
            "suffix_guess": _guess_audio_suffix(raw)
        }

        in_path = _bytes_to_temp_audio(raw)
        wav_path, ffm = _ffmpeg_to_wav_16k_mono(in_path, trim_silence=False)
        dbg["ffmpeg"] = {
            "pass": ffm.get("pass"),
            "rc": ffm.get("rc"),
            "stderr": ffm.get("stderr"),
        }
        dbg["probe"]["in"] = {
            "duration": _probe_duration_sec(ffm.get("probe_in", {})),
            "raw": ffm.get("probe_in", {})
        }
        dbg["probe"]["wav"] = {
            "duration": _probe_duration_sec(ffm.get("probe_out", {})),
            "raw": ffm.get("probe_out", {})
        }

        model = get_model()
        # Cấu hình chống “hallucination”
        result = model.transcribe(
            wav_path,
            language=(lang or "en"),
            task="transcribe",
            fp16=False,
            verbose=False,
            temperature=0.0,
            beam_size=5,                 # dùng beam search quyết định (không dùng best_of)
            logprob_threshold=-0.7,
            no_speech_threshold=0.5,
            condition_on_previous_text=False,
        )
        text = (result.get("text") or "").strip()
        return text, dbg
    finally:
        _safe_remove(in_path)
        _safe_remove(wav_path)

# =========================
# Pronunciation scoring
# =========================
def simple_pron_score(audio_base64: str, expected_text: str, lang: str = "en") -> Dict[str, Any]:
    """
    Trả dict gồm overall/words/details + debug (nếu DEBUG_AUDIO)
    """
    in_path, wav_path = None, None
    try:
        raw = _b64_to_bytes_any(audio_base64)
        _debug_head(raw, "score")
        if not _looks_like_audio(raw):
            raise ValueError("Provided audio does not look like a valid audio file.")

        in_path = _bytes_to_temp_audio(raw)
        wav_path, ffm = _ffmpeg_to_wav_16k_mono(in_path, trim_silence=False)

        model = get_model()
        # Cấu hình giống STT để nhất quán
        result = model.transcribe(
            wav_path,
            language=(lang or "en"),
            task="transcribe",
            fp16=False,
            verbose=False,
            temperature=0.0,
            beam_size=5,
            logprob_threshold=-0.7,
            no_speech_threshold=0.5,
            condition_on_previous_text=False,
        )

        hyp_text = (result.get("text") or "").strip()
        segments = result.get("segments") or []

        # duration = end của segment cuối
        duration = 0.0
        if segments:
            try:
                duration = float(segments[-1].get("end", 0.0)) or 0.0
            except Exception:
                duration = 0.0

        # conf ~ sigmoid(avg_logprob)
        seg_confs = [1.0 / (1.0 + np.exp(-seg.get("avg_logprob", -3.0))) for seg in segments] or [0.5]
        conf = float(np.mean(seg_confs))

        # WER/CER (kẹp 0..1 khi đưa vào công thức)
        ref = (expected_text or "").strip()
        try:
            _wer_raw = float(wer(ref.lower(), hyp_text.lower()))
            _cer_raw = float(cer(ref.lower(), hyp_text.lower()))
        except Exception:
            _wer_raw, _cer_raw = 1.0, 1.0

        wer_cap = min(1.0, max(0.0, _wer_raw))
        cer_cap = min(1.0, max(0.0, _cer_raw))

        # Nội suy timestamps
        hyp_words_timed = []
        for seg in segments:
            seg_text_norm = _normalize_text(seg.get("text", ""))
            words = [w for w in seg_text_norm.split(" ") if w]
            if not words:
                continue
            t0, t1 = float(seg.get("start", 0.0)), float(seg.get("end", 0.0))
            span = max(1e-6, (t1 - t0))
            step = span / len(words)
            for i, w in enumerate(words):
                hyp_words_timed.append({
                    "word": w,
                    "start": t0 + i * step,
                    "end": t0 + (i + 1) * step
                })

        # --- REF words (normalized) ---
        ref = (expected_text or "").strip()
        ref_words = [w for w in _normalize_text(ref).split(" ") if w]

        # --- ALIGN intelligently (bỏ insert khỏi WER/CER) ---
        per_word, aligned_hyp_for_wer = _align_ref_hyp(ref_words, hyp_words_timed, near_ok_ed=1)

        # Nếu toàn bộ cụm ref xuất hiện trong hyp_text (sau normalize) → boost các từ chưa 'ok'
        if ref_words:
            ref_join = " ".join(ref_words)
            if ref_join in _normalize_text(hyp_text):
                for pw in per_word:
                    if pw["status"] != "ok":
                        pw["status"] = "ok"
                        pw["score"] = max(pw["score"], 85)

        # --- WER/CER chỉ tính trên phần đã align (bỏ insert) ---
        try:
            hyp_for_wer = " ".join(aligned_hyp_for_wer) if aligned_hyp_for_wer else hyp_text
            _wer_raw = float(wer(ref.lower(), hyp_for_wer.lower()))
            _cer_raw = float(cer(ref.lower(), hyp_for_wer.lower()))
        except Exception:
            _wer_raw, _cer_raw = 1.0, 1.0

        # --- Clamp và tổng điểm ---
        wer_cap = min(1.0, max(0.0, _wer_raw))
        cer_cap = min(1.0, max(0.0, _cer_raw))

        prosody = _speed_factor(duration or 0.0, len(ref))
        overall = 100 * (0.6 * (1 - wer_cap) + 0.2 * (1 - cer_cap) + 0.2 * conf)
        overall = max(0, min(100, overall * prosody))

        # Gate độ tin cậy thấp
        low_conf = (conf < 0.35 and sum(1 for x in per_word if x["status"] == "ok") == 0)

        sps = (len(ref) / 3) / max(0.1, (duration or 0.0))

        out = {
            "overall": round((overall if not low_conf else min(overall, 50.0)), 1),
            "words": per_word,
            "details": {
                "wer": round(min(100.0, max(0.0, _wer_raw * 100.0)), 2),
                "cer": round(min(100.0, max(0.0, _cer_raw * 100.0)), 2),
                "conf": round(conf, 3),
                "duration": round(float(duration or 0.0), 2),
                "speed_sps": round(float(sps), 2),
                "recognized": hyp_text,
                "low_confidence": low_conf,
            },
        }

        if DEBUG_AUDIO:
            out["debug"] = {
                "ffmpeg": {
                    "pass": ffm.get("pass"),
                    "rc": ffm.get("rc"),
                    "stderr": ffm.get("stderr"),
                },
                "probe": {
                    "in": {
                        "duration": _probe_duration_sec(ffm.get("probe_in", {})),
                        "raw": ffm.get("probe_in", {}),
                    },
                    "wav": {
                        "duration": _probe_duration_sec(ffm.get("probe_out", {})),
                        "raw": ffm.get("probe_out", {}),
                    }
                }
            }

        return out
    finally:
        _safe_remove(in_path)
        _safe_remove(wav_path)


