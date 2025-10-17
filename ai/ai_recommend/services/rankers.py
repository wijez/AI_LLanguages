from datetime import timedelta
from typing import List, Dict, Any, Optional
from .feature_and_rank import _sigmoid, _days_since, _to_dt, SkillCand, WordCand


def rank_skills(
    mis_by_skill: Dict[int, Dict[str, Any]],
    acc_map: Dict[int, Dict[str, float]],
    problem_lesson: Dict[int, int],
    # các “gap” như proficiency, last_practiced nên được kéo từ BE UserSkillStats endpoint (khuyến nghị)
    skill_meta: Dict[int, Dict[str, Any]],  # {skill_id: {'level':int,'proficiency':float,'last_practiced':datetime,'status':str}}
    top_k=5
) -> List[SkillCand]:
    cands: List[SkillCand] = []

    for sid, meta in skill_meta.items():
        if meta.get('status') == 'locked':
            continue

        last_prac = meta.get('last_practiced')
        recency_days = _days_since(last_prac)
        review_urgency = _sigmoid((recency_days - 2.0) / 2.0)
        needs_review = meta.get('needs_review', False)
        review_flag = 0.2 if needs_review else 0.0

        m = mis_by_skill.get(sid, {'mistakes':0,'severity_sum':0.0,'last':None,'sources':{}})
        mistakes = m['mistakes']; severity_sum = m['severity_sum']; src_dist = m['sources']
        error_pressure = _sigmoid(0.8*mistakes + 0.6*severity_sum)

        prof = float(meta.get('proficiency') or 0.0)
        prof_gap = max(0.0, 1.0 - (prof/100.0))
        recency_gap = min(1.0, recency_days/10.0)
        level = int(meta.get('level') or 0)
        difficulty_gap = max(0.0, 1.0 - (level/5.0))

        am = acc_map.get(sid, {})
        acc = am.get('acc', None)
        acc_gap = 0.0 if acc is None else max(0.0, (80.0 - acc)/80.0)

        w = {'review_urgency':0.28,'review_flag':0.10,'error_pressure':0.27,'prof_gap':0.15,'recency_gap':0.10,'difficulty_gap':0.05,'acc_gap':0.05}
        score = (w['review_urgency']*review_urgency + w['review_flag']*review_flag + w['error_pressure']*error_pressure +
                 w['prof_gap']*prof_gap + w['recency_gap']*recency_gap + w['difficulty_gap']*difficulty_gap + w['acc_gap']*acc_gap)

        lesson_id = problem_lesson.get(sid)  # fallback: FE có thể chọn lesson đầu tiên của skill nếu None

        rec_type = 'review' if (review_urgency>0.6 or mistakes>0 or needs_review) else 'practice'
        if level <= 1 and (acc is not None and acc >= 90) and mistakes == 0:
            rec_type = 'challenge'

        reasons = []
        if recency_days >= 2: reasons.append(f"Đã {int(recency_days)} ngày chưa luyện")
        if mistakes > 0: reasons.append(f"{mistakes} lỗi gần đây")
        if acc is not None and acc < 80: reasons.append(f"Điểm tương tác ~{acc:.0f}% (<80%)")

        cands.append(SkillCand(skill_id=sid, lesson_id=lesson_id, score=round(float(score),4),
                               rec_type=rec_type, reasons=reasons[:3]))

    return sorted(cands, key=lambda c: -c.score)[:top_k]


def rank_words(mistakes: List[Dict[str, Any]], top_n=10, lookback_days=14) -> List[WordCand]:
    from django.utils import timezone
    since = timezone.now() - timedelta(days=lookback_days)

    agg: Dict[int, Dict[str, Any]] = {}
    for m in mistakes:
        wid = m.get("word") or m.get("word_id") or None
        if not wid:
            continue
        ts = _to_dt(m.get("timestamp"))
        if ts and ts < since:
            continue
        d = agg.setdefault(wid, {"mistakes":0, "sum_score":0.0, "cnt_score":0, "sum_conf":0.0, "cnt_conf":0, "last":None})
        d["mistakes"] += 1
        s = m.get("score", None)
        if s is not None:
            d["sum_score"] += float(s); d["cnt_score"] += 1
        c = m.get("confidence", None)
        if c is not None:
            d["sum_conf"] += float(c); d["cnt_conf"] += 1
        if (not d["last"]) or (ts and ts > d["last"]):
            d["last"] = ts

    cands: List[WordCand] = []
    for wid, d in agg.items():
        mistakes = d["mistakes"]
        avg_score = (d["sum_score"]/d["cnt_score"]) if d["cnt_score"]>0 else 0.5
        avg_conf = (d["sum_conf"]/d["cnt_conf"]) if d["cnt_conf"]>0 else 0.5
        last_days = _days_since(d["last"])

        m_term = min(1.0, mistakes/5.0)
        score = 0.45*m_term + 0.30*(1.0-avg_score) + 0.20*(1.0-avg_conf) + 0.05*_sigmoid((14-last_days)/2.5)

        reasons = []
        if mistakes>0: reasons.append(f"{mistakes} lỗi/{lookback_days} ngày")
        if avg_score<0.7: reasons.append(f"Điểm trung bình ~{avg_score:.2f}")
        if avg_conf<0.7: reasons.append(f"Confidence thấp ~{avg_conf:.2f}")

        cands.append(WordCand(word_id=wid, score=round(float(score),4), reasons=reasons[:3]))

    return sorted(cands, key=lambda c: -c.score)[:top_n]
