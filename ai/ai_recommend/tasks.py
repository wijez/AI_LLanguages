import time
import logging
from celery import shared_task
from django.conf import settings

from .services.exporter import export_snapshot
from .ml.trainer import train_from_snapshot

logger = logging.getLogger(__name__)

@shared_task(name="ai.tasks.train_ai_model_task")
def train_ai_model_task():
    """
    Quy trình chuẩn hóa (Pipeline):
    Bước 1: Export Snapshot (DB -> Parquet trên MinIO) - Có features.parquet & labels.parquet
    Bước 2: Train Model (Parquet -> Joblib)
    """
    # 1. Tạo ID cho snapshot (theo thời gian thực)
    snapshot_id = f"snap_{int(time.time())}"
    logger.info(f"Bắt đầu quy trình AI định kỳ. Snapshot ID: {snapshot_id}")

    try:
        # =========================================================
        # BƯỚC 1: TẠO SNAPSHOT (Data Engineering)
        # Hàm này sẽ tạo ra 2 file: features.parquet và labels.parquet
        # =========================================================
        logger.info("Bước 1: Đang export dữ liệu ra MinIO...")
        export_result = export_snapshot(snapshot_id)
        
        # Kiểm tra nếu export thất bại hoặc không có dữ liệu
        if not export_result or not export_result.get("features_uri"):
            logger.warning("Export snapshot thất bại hoặc không có dữ liệu. Dừng training.")
            return "Skipped: No data exported"

        logger.info(f"Export thành công: {export_result}")

        # =========================================================
        # BƯỚC 2: HUẤN LUYỆN MODEL (Machine Learning)
        # Hàm này đọc 2 file parquet vừa tạo để train ra file .joblib
        # =========================================================
        logger.info("Bước 2: Đang huấn luyện model...")
        
        # Các tham số train (có thể lưu trong settings hoặc DB config)
        training_params = {
            "max_depth": 5,
            "learning_rate": 0.1,
            "n_estimators": 100
        }
        
        train_result = train_from_snapshot(snapshot_id, params=training_params)
        
        logger.info(f"Huấn luyện hoàn tất. Model Version: {train_result.get('version')}")
        return {
            "status": "success",
            "snapshot_id": snapshot_id,
            "model_version": train_result.get('version'),
            "val_auc": train_result.get('val_auc')
        }

    except Exception as e:
        logger.error(f"Lỗi nghiêm trọng trong train_ai_model_task: {e}", exc_info=True)
        # Re-raise để Celery ghi nhận trạng thái Failure
        raise e