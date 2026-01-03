import os
import logging
import pandas as pd
from typing import Dict, Any, List
from django.conf import settings
from django.db.models import F

from ai_recommend.models import FeedbackLoop
from ai_recommend.ml.features import build_features
from ai_recommend.ml.trainer import _s3_opts
from ai_recommend.clients.be_client import BEClient
from ai_recommend.auth.jwt_session import JWTSession

logger = logging.getLogger(__name__)


def export_snapshot(snapshot_id: str) -> Dict[str, str]:
    """
    ETL Process:
    1. Extract Labels: Từ bảng FeedbackLoop (DB) -> labels.parquet
    2. Extract Features: Từ API Mistakes & SkillStats (BE) -> features.parquet
    3. Load: Upload lên MinIO để trainer.py sử dụng.
    """
    bucket = os.getenv("MINIO_BUCKET", "ai-snapshots")
    prefix = f"snapshots/{snapshot_id}"
    
    # Định nghĩa đường dẫn S3 đầu ra
    s3_path_labels = f"s3://{bucket}/{prefix}/labels.parquet"
    s3_path_features = f"s3://{bucket}/{prefix}/features.parquet"
    
    logger.info(f"Starting export for snapshot: {snapshot_id}")

    # =========================================================================
    # BƯỚC 1: XÂY DỰNG LABELS (Y) TỪ FEEDBACK LOOP
    # =========================================================================
    logger.info("Building LABELS from FeedbackLoop...")

    feedbacks_qs = FeedbackLoop.objects.filter(
        outcome__in=['completed', 'failed', 'skipped']
    ).select_related('recommendation').values(
        'created_at', 
        enrollment_id=F('recommendation__enrollment_id'),
        user_id=F('recommendation__user_id'),
        outcome_val=F('outcome'),
    )

    if not feedbacks_qs.exists():
        logger.warning("No feedback data found. Cannot create snapshot.")
        return {}

    df_raw_labels = pd.DataFrame(list(feedbacks_qs))
    df_raw_labels['is_success'] = df_raw_labels['outcome_val'].apply(lambda x: 1 if x == 'completed' else 0)

    # Aggregation: Mỗi enrollment_id chỉ được xuất hiện 1 lần trong file labels
    df_labels = df_raw_labels.groupby('enrollment_id')['is_success'].max().reset_index()
    df_labels.rename(columns={'is_success': 'target_completed'}, inplace=True)
    
    # Upload Labels to S3
    logger.info(f"Uploading {len(df_labels)} label rows to {s3_path_labels}...")
    try:
        df_labels.to_parquet(s3_path_labels, storage_options=_s3_opts())
    except Exception as e:
        logger.error(f"Failed to upload labels: {e}")
        raise e

    # =========================================================================
    # BƯỚC 2: XÂY DỰNG FEATURES (X) TỪ BACKEND
    # =========================================================================
    logger.info("Building FEATURES from Backend (Mistakes + SkillStats)...")

    target_user_ids = df_raw_labels['user_id'].unique()
    
    jwt_sess = JWTSession(
        base_url=settings.BE_API_BASE_URL,            
        username=settings.BE_JWT_USERNAME,
        password=settings.BE_JWT_PASSWORD,
        token_url=getattr(settings, "BE_JWT_TOKEN_URL", "/api/token/"),
        refresh_url=getattr(settings, "BE_JWT_REFRESH_URL", "/api/token/refresh/"),
    )
    client = BEClient(base_url=settings.BE_API_BASE_URL, jwt_session=jwt_sess)

    raw_mistakes_list = []
    raw_stats_list = []  

    count_users = len(target_user_ids)
    for idx, uid in enumerate(target_user_ids):
        if idx % 10 == 0:
            logger.info(f"Fetching data for user {idx+1}/{count_users}...")
        try:
            # 1. Fetch Mistakes
            mistakes = list(client.list_mistakes(user_id=uid, language="en"))
            for m in mistakes:
                eid = m.get('enrollment') or m.get('enrollment_id')
                if eid:
                    raw_mistakes_list.append({
                        "enrollment_id": eid,
                        "score": float(m.get('score', 0) or 0)
                    })
            stats = list(client.list_skill_stats(user_id=uid, language="en"))
            for s in stats:
                eid = s.get('enrollment') or s.get('enrollment_id')
                if eid:
                    raw_stats_list.append({
                        "enrollment_id": eid,
                        "proficiency_score": float(s.get('proficiency_score', 0) or 0),
                        "xp": int(s.get('xp', 0) or 0),
                        "last_practiced": s.get('last_practiced')
                    })

        except Exception as e:
            logger.warning(f"Error fetching data for user {uid}: {e}")

    # Build Features DataFrame
    df_raw_mistakes = pd.DataFrame(raw_mistakes_list)
    df_raw_stats = pd.DataFrame(raw_stats_list) if raw_stats_list else None 

    # Gọi hàm build_features với cả 2 nguồn dữ liệu
    df_features = build_features(df_raw_mistakes, df_raw_stats)

    # Upload Features to S3
    logger.info(f"Uploading {len(df_features)} feature rows to {s3_path_features}...")
    try:
        df_features.to_parquet(s3_path_features, storage_options=_s3_opts())
    except Exception as e:
        logger.error(f"Failed to upload features: {e}")
        raise e

    logger.info("Snapshot export completed successfully.")
    
    return {
        "features_uri": s3_path_features,
        "labels_uri": s3_path_labels
    }