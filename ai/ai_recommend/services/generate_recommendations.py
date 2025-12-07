from typing import List, Dict, Any, Optional
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.db import transaction
from django.utils.crypto import get_random_string

from ai_recommend.clients.be_client import BEClient
from ai_recommend.services.feature_and_rank import aggregate_from_be
from ai_recommend.services.rankers import rank_skills, rank_words
from ai_recommend.models import Recommendation, AIModelVersion
from ..auth.jwt_session import JWTSession
from django.conf import settings



def _parse_iso_dt(value: Optional[str]):
    """Parse ISO datetime string (kể cả dạng có 'Z') -> aware datetime (UTC)."""
    if not value:
        return None
    try:
        v = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)
        return dt
    except Exception:
        return None


def generate_recommendations_for_user(
    user_id: int,
    enrollment_id: int,
    language: str,
    top_k: int = 5,
    top_n_words: int = 10
) -> List[int]:
    """
    Kéo dữ liệu Mistake/Interaction/SkillStats từ BE rồi tạo Recommendation trong DB của ai_recommend.
    Yêu cầu settings:
      - BE_API_BASE_URL
      - (tuỳ chọn) BE_API_TOKEN
      - (khuyến nghị) BE_API_KEY  -> gửi header X-Internal-Api-Key
    """
    jwt_sess = JWTSession(
        base_url=settings.BE_API_BASE_URL,            
        username=settings.BE_JWT_USERNAME,
        password=settings.BE_JWT_PASSWORD,
        token_url=getattr(settings, "BE_JWT_TOKEN_URL", "/api/token/"),
        refresh_url=getattr(settings, "BE_JWT_REFRESH_URL", "/api/token/refresh/"),
    )
    client = BEClient(base_url=settings.BE_API_BASE_URL, jwt_session=jwt_sess)

    mistakes = list(client.list_mistakes(user_id=user_id, language=language))
    interactions = list(client.list_interactions(user_id=user_id, language=language))

    skill_meta: Dict[int, Dict[str, Any]] = {}
    try:
        for row in client.list_skill_stats(user_id=user_id, language=language):
            sid = row["skill_id"]
            skill_meta[sid] = {
                "level": row.get("level", 0),
                "proficiency": row.get("proficiency_score", 0.0),
                "last_practiced": _parse_iso_dt(row.get("last_practiced")),
                "status": row.get("status", "available"),
                "needs_review": row.get("needs_review", False),
            }
    except Exception:
        pass

    mis_by_skill, acc_map, problem_lesson = aggregate_from_be(mistakes, interactions)

    # 4) Xếp hạng
    skill_cands = rank_skills(mis_by_skill, acc_map, problem_lesson, skill_meta, top_k=top_k)
    word_cands = rank_words(mistakes, top_n=top_n_words)

    # 5) Ghi xuống bảng Recommendation
    batch_id = get_random_string(16)
    model_used = AIModelVersion.objects.order_by('-trained_at').first()

    rec_ids: List[int] = []
    with transaction.atomic():
        for c in skill_cands:
            r = Recommendation.objects.create(
                user_id=user_id,
                enrollment_id=enrollment_id,
                skill_id=c.skill_id,
                lesson_id=c.lesson_id,
                word_id=None,
                rec_type=c.rec_type,         
                reasons=c.reasons,          
                language=language,            
                batch_id=batch_id,           
                priority_score=c.score,
                model_used=model_used,
            )
            rec_ids.append(r.id)

        for w in word_cands:
            r = Recommendation.objects.create(
                user_id=user_id,
                enrollment_id=enrollment_id,
                skill_id=None,
                lesson_id=None,
                word_id=w.word_id,
                rec_type='word',
                reasons=w.reasons,
                language=language,
                batch_id=batch_id,
                priority_score=w.score,
                model_used=model_used,
            )
            rec_ids.append(r.id)

    return rec_ids
