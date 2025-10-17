from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone as pytimezone

from django.utils import timezone

def _to_dt(s: Optional[str]):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

def _days_since(dt):
    if not dt:
        return 999.0
    now = timezone.now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=pytimezone.utc)
    return max(0.0, (now - dt).total_seconds() / 86400.0)

def _sigmoid(x: float) -> float:
    import math
    return 1.0 / (1.0 + math.exp(-x))


@dataclass
class SkillCand:
    skill_id: int
    lesson_id: Optional[int]
    score: float
    rec_type: str
    reasons: List[str]

@dataclass
class WordCand:
    word_id: int
    score: float
    reasons: List[str]


def aggregate_from_be(mistakes: List[Dict[str, Any]], interactions: List[Dict[str, Any]]):
    """
    Từ JSON của BE → gom per-skill & per-word.
    Kỳ vọng mistakes fields: skill (id), lesson (id), word (id), score, confidence, timestamp, source
    Kỳ vọng interactions fields: skill (id), lesson (id), action, value, success, duration_seconds, created_at
    """

    # === Mistake per-skill ===
    mis_by_skill: Dict[int, Dict[str, Any]] = {}
    since7 = timezone.now() - timedelta(days=7)
    for m in mistakes:
        sid = m.get("skill") or m.get("skill_id") or 0
        ts = _to_dt(m.get("timestamp"))
        if not sid:
            continue
        if ts and ts < since7:
            continue
        d = mis_by_skill.setdefault(sid, {"mistakes": 0, "severity_sum": 0.0, "last": None, "sources": {}})
        d["mistakes"] += 1
        score = m.get("score", None)
        severity = 1.0 - (float(score) if score is not None else 0.5)
        d["severity_sum"] += severity
        if (not d["last"]) or (ts and ts > d["last"]):
            d["last"] = ts
        src = (m.get("source") or "other")
        d["sources"][src] = d["sources"].get(src, 0) + 1

    # === Accuracy/success per-skill ===
    acc_map: Dict[int, Dict[str, float]] = {}
    since30 = timezone.now() - timedelta(days=30)
    for it in interactions:
        sid = it.get("skill") or it.get("skill_id") or 0
        if not sid:
            continue
        ts = _to_dt(it.get("created_at"))
        if ts and ts < since30:
            continue
        d = acc_map.setdefault(sid, {"sum_value": 0.0, "cnt_value": 0, "sum_success": 0.0, "cnt": 0})
        v = it.get("value", None)
        if v is not None:
            d["sum_value"] += float(v)
            d["cnt_value"] += 1
        succ = it.get("success", None)
        if succ is not None:
            d["sum_success"] += 1.0 if succ else 0.0
        d["cnt"] += 1

    for sid, d in acc_map.items():
        d["acc"] = (d["sum_value"]/d["cnt_value"]) if d["cnt_value"]>0 else None
        d["success_rate"] = (d["sum_success"]/d["cnt"]) if d["cnt"]>0 else None

    # === Lesson with most mistakes per skill ===
    problem_lesson: Dict[int, int] = {}
    cnt_per_lesson: Dict[int, int] = {}
    since14 = timezone.now() - timedelta(days=14)
    for m in mistakes:
        sid = m.get("skill") or m.get("skill_id") or 0
        lsn = m.get("lesson") or m.get("lesson_id") or None
        ts = _to_dt(m.get("timestamp"))
        if not sid or not lsn or (ts and ts < since14):
            continue
        cnt_per_lesson[lsn] = cnt_per_lesson.get(lsn, 0) + 1
    # assign top lesson per-skill (best effort)
    # (Không đủ metadata để map ngược skill ← lesson ở đây; giả định BE đã ghi đúng skill trong mistake)
    # Nếu muốn chính xác hơn, BE nên trả về cả skill_id kèm lesson_id trong mistakes.
    for m in mistakes:
        sid = m.get("skill") or 0
        lsn = m.get("lesson") or None
        if not sid or not lsn:
            continue
        # pick lesson with max count overall within that skill
        # (đơn giản: lesson có count cao nhất sẽ thắng)
        if problem_lesson.get(sid) is None:
            problem_lesson[sid] = lsn
        else:
            if cnt_per_lesson.get(lsn, 0) > cnt_per_lesson.get(problem_lesson[sid], 0):
                problem_lesson[sid] = lsn

    return mis_by_skill, acc_map, problem_lesson
