from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone as pytimezone

from django.db.models.fields import parse_datetime
from django.utils import timezone

def _to_dt(s: Optional[str]):
    if not s:
        return None
    s_clean = str(s).strip()
    s_clean = s_clean.replace("Z", "+00:00")
    s_clean = s_clean.replace(" ", "T")
    if s_clean.endswith("+00"):
        s_clean = s_clean[:-3] + "+00:00"
    
    try:
        dt = datetime.fromisoformat(s_clean)
    except ValueError:
        try:
            dt = parse_datetime(s)
        except Exception:
            return None

    if dt is None:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.utc)
    
    return dt

def _days_since(dt):
    if not dt:
        return 999.0
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.utc)
    now = timezone.now()
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

    now = timezone.now()

    #  Mistake per-skill
    mis_by_skill: Dict[int, Dict[str, Any]] = {}
    since7 = now - timedelta(days=7)
    
    for m in mistakes:
        sid = m.get("skill") or m.get("skill_id") or 0
        if not sid:
            continue
            
        ts = _to_dt(m.get("timestamp"))
        
        #  dữ liệu trong 7 ngày gần nhất 
        if ts and ts < since7:
            continue

        d = mis_by_skill.setdefault(
            sid, 
            {
                "mistakes": 0, 
                "severity_sum": 0.0, 
                "last": None, 
                "sources": {}
            }
        )

        if ts and (not d["last"] or ts > d["last"]):
            d["last"] = ts
            
        d["mistakes"] += 1
        
        score = m.get("score")
        # Score càng thấp -> Severity càng cao (mặc định 0.5 nếu null)
        severity = 1.0 - (float(score) if score is not None else 0.5)
        d["severity_sum"] += severity

        src = (m.get("source") or "other")
        d["sources"][src] = d["sources"].get(src, 0) + 1

    # === 2. Accuracy/success per-skill (Window: 30 days) ===
    acc_map: Dict[int, Dict[str, float]] = {}
    since30 = now - timedelta(days=30)
    
    for it in interactions:
        sid = it.get("skill") or it.get("skill_id") or 0
        if not sid:
            continue
            
        ts = _to_dt(it.get("created_at"))
        if ts and ts < since30:
            continue
            
        d = acc_map.setdefault(sid, {"sum_value": 0.0, "cnt_value": 0, "sum_success": 0.0, "cnt": 0})
        
        v = it.get("value")
        if v is not None:
            d["sum_value"] += float(v)
            d["cnt_value"] += 1
            
        succ = it.get("success")
        if succ is not None:
            d["sum_success"] += 1.0 if succ else 0.0
        d["cnt"] += 1

    for sid, d in acc_map.items():
        d["acc"] = (d["sum_value"]/d["cnt_value"]) if d["cnt_value"]>0 else None
        d["success_rate"] = (d["sum_success"]/d["cnt"]) if d["cnt"]>0 else None

    # === 3. Lesson with most mistakes per skill (Window: 14 days) ===
    # Logic tối ưu: Gom nhóm 1 lần rồi tìm Max
    problem_lesson: Dict[int, int] = {}
    skill_lesson_counter: Dict[int, Dict[int, int]] = {} 
    since14 = now - timedelta(days=14)

    for m in mistakes:
        sid = m.get("skill") or m.get("skill_id") or 0
        lsn = m.get("lesson") or m.get("lesson_id")
        ts = _to_dt(m.get("timestamp"))

        # Bỏ qua nếu thiếu thông tin hoặc quá cũ ( > 14 ngày)
        if not sid or not lsn or (ts and ts < since14):
            continue
        
        if sid not in skill_lesson_counter:
            skill_lesson_counter[sid] = {}
        
        skill_lesson_counter[sid][lsn] = skill_lesson_counter[sid].get(lsn, 0) + 1

    # Tìm lesson có số lỗi cao nhất trong mỗi skill
    for sid, lessons_map in skill_lesson_counter.items():
        if lessons_map:
            # Lấy key (lesson_id) có value lớn nhất
            best_lesson = max(lessons_map, key=lessons_map.get)
            problem_lesson[sid] = best_lesson

    return mis_by_skill, acc_map, problem_lesson
