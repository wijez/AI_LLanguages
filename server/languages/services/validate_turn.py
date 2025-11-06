import re, math, unicodedata
from collections import Counter
from difflib import SequenceMatcher
from languages.services.ollama_client import embed_one

# ==== patterns ====
PHONE_RE = re.compile(r"\+?\d[\d\-\s]{6,}\d")
TIME_RE  = re.compile(r"\b([01]?\d|2[0-3])\s*[:.]\s*[0-5]\d(\s*(am|pm))?\b", re.I)

# $80 / 80$ / 80 dollars / 80 usd / eighty dollars (số chữ vẫn để, nhưng gom các cụm rõ ràng)
CURRENCY_WORDS = r"(dollars?|bucks?|usd|euros?|eur|pounds?|gbp|yen|jpy|vnd|dong)"
MONEY_RE = re.compile(
    rf"(\$|\€|\£|\¥)\s*\d+(\.\d+)?|\d+(\.\d+)?\s*({CURRENCY_WORDS})",
    re.I
)

# Một số viết tắt phổ biến
CONTRACTIONS = {
    "i'm": "i am", "we're": "we are", "you're": "you are",
    "they're": "they are", "it's": "it is", "that's": "that is",
    "there's": "there is", "i've": "i have", "we've": "we have",
    "can't": "cannot", "won't": "will not", "don't": "do not",
    "didn't": "did not", "couldn't": "could not", "wouldn't": "would not",
    "shouldn't": "should not", "i'll": "i will", "we'll": "we will",
    "you'll": "you will", "they'll": "they will", "let's": "let us",
}

# filler words cần bỏ qua khi so khớp tokens
FILLERS = {"uh", "um", "er", "ah", "uhm", "hmm", "like", "you", "know"}

# stopwords tối giản để giảm nhiễu lexical
STOPWORDS = {"a", "an", "the", "to", "for", "at", "is", "am", "are", "of", "and"}


def _ascii_quotes(s: str) -> str:
    # chuẩn hoá unicode → ascii (thay smart quotes)
    tbl = {
        ord("’"): "'",
        ord("‘"): "'",
        ord("“"): '"',
        ord("”"): '"',
        ord("–"): "-",
        ord("—"): "-",
        ord("…"): "...",
        160: 32,  # NBSP → space
    }
    return s.translate(tbl)

def _expand_contractions(s: str) -> str:
    for k, v in CONTRACTIONS.items():
        s = re.sub(rf"\b{k}\b", v, s)
    return s

def _normalize(s: str) -> str:
    s = _ascii_quotes(s or "")
    s = unicodedata.normalize("NFKC", s).lower().strip()
    s = _expand_contractions(s)

    # placeholders
    s = re.sub(PHONE_RE, "<PHONE>", s)
    s = re.sub(TIME_RE, "<TIME>", s)
    s = re.sub(MONEY_RE, "<MONEY>", s)

    # bỏ hầu hết punctuation, giữ chữ số/chữ và placeholders <>
    s = re.sub(r"[^a-z0-9<>\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _tokens(s: str):
    toks = re.findall(r"[a-z0-9<>]+", s)
    # bỏ fillers/stopwords nhẹ
    return [t for t in toks if t not in FILLERS and t not in STOPWORDS]

def _seq_ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

def _token_f1(exp_toks, usr_toks):
    if not exp_toks or not usr_toks:
        return 0.0
    ce = Counter(exp_toks); cu = Counter(usr_toks)
    overlap = sum(min(ce[w], cu[w]) for w in set(ce) & set(cu))
    p = overlap / max(1, sum(cu.values()))
    r = overlap / max(1, sum(ce.values()))
    return 2 * p * r / max(1e-9, (p + r))

def _token_set_ratio(exp_toks, usr_toks):
    se, su = set(exp_toks), set(usr_toks)
    if not se or not su:
        return 0.0
    inter = len(se & su)
    # dùng mẫu giống token_set_ratio: intersection / min(lenA, lenB)
    return inter / float(min(len(se), len(su)))

def _lexical_score(exp_norm: str, usr_norm: str):
    seq = _seq_ratio(exp_norm, usr_norm)
    expt = _tokens(exp_norm)
    usrt = _tokens(usr_norm)
    f1 = _token_f1(expt, usrt)
    ts = _token_set_ratio(expt, usrt)
    return max(seq, f1, ts), {
        "seq": round(seq, 4),
        "f1": round(f1, 4),
        "set": round(ts, 4),
        "exp_tokens": expt,
        "usr_tokens": usrt,
    }

def _to_list(vec):
    if vec is None:
        return None
    if isinstance(vec, list):
        return vec
    try:
        return list(vec)
    except Exception:
        if hasattr(vec, "tolist"):
            return vec.tolist()
        return None

def _cosine(u, v):
    # phòng khi độ dài lệch → cắt về min len
    n = min(len(u), len(v))
    if n == 0:
        return 0.0
    if len(u) != len(v):
        u = u[:n]; v = v[:n]
    dot = sum(a*b for a, b in zip(u, v))
    nu = math.sqrt(sum(a*a for a in u)) or 1e-9
    nv = math.sqrt(sum(b*b for b in v)) or 1e-9
    return dot / (nu * nv)

# ========== THRESHOLDS (tinh chỉnh được) ==========
COS_MAIN   = 0.78  # cosine cứng
COS_SOFT   = 0.72  # cosine mềm + lexical cao
LEX_STRONG = 0.82  # lexical mạnh khi cosine mềm
LEX_HARD   = 0.88  # chỉ lexical đủ cao là pass

def score_user_turn(expected_text: str, expected_vec, user_text: str):
    """
    expected_text: câu chuẩn
    expected_vec : vector trong DB (có cũng được, không có cũng ok)
    user_text    : người học nói (đã STT)
    """
    exp_norm = _normalize(expected_text or "")
    usr_norm = _normalize(user_text or "")

    # lexical
    lex, lex_dbg = _lexical_score(exp_norm, usr_norm)

    # semantic: embed cả 2 NORMALIZED strings
    evec_norm = embed_one(exp_norm)  # luôn embed lại để nhất quán chuẩn hoá
    uvec      = embed_one(usr_norm)

    cos1 = _cosine(uvec, evec_norm)

    # nếu DB có vec, cũng thử với vec đó rồi lấy max (tránh lệch cách embed cũ)
    cos2 = None
    ev_db = _to_list(expected_vec)
    if ev_db:
        cos2 = _cosine(uvec, ev_db)

    cos = max(cos1, cos2) if cos2 is not None else cos1

    passed = (cos >= COS_MAIN) or (cos >= COS_SOFT and lex >= LEX_STRONG) or (lex >= LEX_HARD)

    return {
        "cosine": round(cos, 4),
        "lexical": round(lex, 4),
        "passed": bool(passed),
        "debug": {
            "expected_norm": exp_norm,
            "user_norm": usr_norm,
            "cos_norm": round(cos1, 4),
            **({"cos_db": round(cos2, 4)} if cos2 is not None else {}),
            **lex_dbg,
            "thresholds": {
                "COS_MAIN": COS_MAIN, "COS_SOFT": COS_SOFT,
                "LEX_STRONG": LEX_STRONG, "LEX_HARD": LEX_HARD
            }
        }
    }



def make_hint(text: str, max_chars: int = 80) -> str:
    s = " ".join((text or "").split())
    if len(s) <= max_chars:
        return s
    cut = s[:max_chars]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut + "…"
