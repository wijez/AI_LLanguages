from celery import shared_task

from .ml.features import build_features
from django.utils import timezone
from datetime import timedelta
from .models import Recommendation
import time
import pandas as pd
import logging
from celery import shared_task
from django.conf import settings

# Import các client và helpers bạn đã tạo
from .auth.jwt_session import JWTSession
from .clients.be_client import BEClient
from .ml.features import build_features
from .ml.trainer import  _snapshot_paths, _s3_opts, train_from_snapshot

logger = logging.getLogger(__name__)

def get_be_client() -> BEClient:
    """Khởi tạo một BEClient đã được xác thực."""
    session = JWTSession(
        base_url=settings.BE_API_BASE_URL,
        username=settings.BE_JWT_USERNAME,
        password=settings.BE_JWT_PASSWORD,
        token_url=settings.BE_JWT_TOKEN_URL,
        refresh_url=settings.BE_JWT_REFRESH_URL,
    )
    # Tự động đăng nhập lần đầu tiên khi cần
    # session.login() 
    return BEClient(base_url=settings.BE_API_BASE_URL, jwt_session=session)

@shared_task(name="ai.tasks.train_ai_model_task")
def train_ai_model_task():
    """
    Tác vụ Celery định kỳ để lấy dữ liệu từ BE, tạo snapshot và train model.
    """
    logger.info("Bắt đầu tác vụ train_ai_model_task...")
    
    try:
        client = get_be_client()
        #  điều chỉnh be_client.py để user_id/language là optional
        logger.info("Đang lấy dữ liệu 'mistakes' từ BE...")
        mistakes = list(client.list_mistakes(user_id=None, language=None))
        if not mistakes:
            logger.warning("Không tìm thấy dữ liệu 'mistakes'. Bỏ qua training.")
            return "No mistake data found."
            
        logger.info("Đang lấy dữ liệu 'interactions' (labels) từ BE...")
        interactions = list(client.list_interactions(user_id=None, language=None))
        if not interactions:
            logger.warning("Không tìm thấy dữ liệu 'interactions'. Bỏ qua training.")
            return "No interaction data found."

        df_mistakes = pd.DataFrame(mistakes)
        df_interactions = pd.DataFrame(interactions) # Dữ liệu thô
        
        # 2. Xây dựng features (X) (đã nhóm theo enrollment_id)
        logger.info("Đang xây dựng features...")
        df_features = build_features(df_mistakes) # Đây là X (features)
        logger.info("Đang xây dựng labels (Y)...")
        if "enrollment_id" not in df_interactions.columns:
            if "enrollment" in df_interactions.columns:
                df_interactions = df_interactions.rename(columns={"enrollment": "enrollment_id"})
            else:
                raise KeyError("Dữ liệu 'interactions' từ BE không chứa cột 'enrollment_id' hoặc 'enrollment'.")

        # Tạo label: 1 nếu enrollment có tương tác thành công, 0 nếu không
        df_labels_agg = df_interactions.groupby("enrollment_id").agg(
            total_interactions=pd.NamedAgg(column="success", aggfunc="count"),
            successful_interactions=pd.NamedAgg(column="success", aggfunc="sum")
        ).reset_index()

        # Định nghĩa target: ví dụ, tỉ lệ thành công > 50%
        # (Nếu total_interactions = 0, phép chia sẽ lỗi, nhưng logic groupby đảm bảo count >= 1)
        df_labels_agg["target_completed"] = (
            (df_labels_agg["successful_interactions"] / df_labels_agg["total_interactions"]) > 0.5
        ).astype(int)
        # 3. Lưu snapshot vào MinIO
        snapshot_id = f"snap_{int(time.time())}"
        paths = _snapshot_paths(snapshot_id)
        s3_opts = _s3_opts()

        logger.info(f"Đang lưu features vào: {paths['features']}")
        df_features.to_parquet(paths["features"], storage_options=s3_opts, index=False)
        
        logger.info(f"Đang lưu labels vào: {paths['labels']}")
        # Lưu file labels ĐÃ ĐƯỢC TỔNG HỢP (agg)
        df_labels_agg.to_parquet(paths["labels"], storage_options=s3_opts, index=False)

        # 4. Huấn luyện model
        logger.info(f"Bắt đầu huấn luyện từ snapshot: {snapshot_id}")
        
        # Lấy params (ví dụ: từ settings hoặc để mặc định)
        training_params = {"max_depth": 5} 
        
        result = train_from_snapshot(snapshot_id, params=training_params)
        
        logger.info(f"Huấn luyện hoàn tất. Kết quả: {result}")
        return result

    except Exception as e:
        logger.error(f"Lỗi nghiêm trọng trong train_ai_model_task: {e}", exc_info=True)
        raise e