from __future__ import annotations
import os, json, time
from typing import Dict, Any
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score
from sklearn.ensemble import GradientBoostingClassifier
import joblib
from django.conf import settings
import math 
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

def _s3_opts():
    return {
        "key": os.getenv("MINIO_ACCESS_KEY"),
        "secret": os.getenv("MINIO_SECRET_KEY"),
        "client_kwargs": {"endpoint_url": os.getenv("MINIO_ENDPOINT")},
    }

def _snapshot_paths(snapshot_id: str) -> Dict[str,str]:
    bucket = os.getenv("MINIO_BUCKET", "ai-snapshots")
    prefix = f"snapshots/{snapshot_id}"
    return {
        "features": f"s3://{bucket}/{prefix}/features.parquet",
        "labels":   f"s3://{bucket}/{prefix}/labels.parquet",
    }

def _save_model_artifact(obj: dict, snapshot_id: str) -> str:
    use_minio = os.getenv("USE_MINIO_MODEL", "0") == "1"
    ts = int(time.time())
    fname = f"gbm_{snapshot_id}_{ts}.joblib"

    if use_minio:
        import io, boto3
        bucket = os.getenv("MINIO_BUCKET", "ai-snapshots")
        key = f"models/{fname}"
        bio = io.BytesIO()
        joblib.dump(obj, bio)
        bio.seek(0)
        s3 = boto3.client(
            "s3",
            endpoint_url=os.getenv("MINIO_ENDPOINT"),
            aws_access_key_id=os.getenv("MINIO_ACCESS_KEY"),
            aws_secret_access_key=os.getenv("MINIO_SECRET_KEY"),
            region_name=os.getenv("MINIO_REGION", "us-east-1"),
        )
        s3.put_object(Bucket=bucket, Key=key, Body=bio.getvalue(), ContentType="application/octet-stream")
        return f"s3://{bucket}/{key}"

    os.makedirs(settings.MODEL_DIR, exist_ok=True)
    path = os.path.join(settings.MODEL_DIR, fname)
    joblib.dump(obj, path)
    return path

def train_from_snapshot(snapshot_id: str, params: Dict[str,Any]) -> Dict[str,Any]:
    from ..models import TrainingRun, AIModelVersion

    paths = _snapshot_paths(snapshot_id)
    
    try:
        X = pd.read_parquet(paths["features"], storage_options=_s3_opts())
        ydf = pd.read_parquet(paths["labels"],   storage_options=_s3_opts())
    except Exception as e:
        logger.error(f"Cannot read parquet files from MinIO: {e}")
        # Re-raise để task biết là lỗi hạ tầng/network
        raise e

    # Validation
    if "enrollment_id" not in X.columns:
        raise ValueError("features.parquet (X) missing 'enrollment_id' column")
    if "enrollment_id" not in ydf.columns:
        raise ValueError("labels.parquet (Y) missing 'enrollment_id' column")
    if "target_completed" not in ydf.columns:
        raise ValueError("labels.parquet (Y) missing 'target_completed' column")

    # Merge Data
    df = X.merge(
        ydf[["enrollment_id", "target_completed"]],
        on="enrollment_id",
        how="left"
    ).copy()
    
    # Fillna: Coi như chưa hoàn thành (0) nếu thiếu label
    df["target_completed"] = df["target_completed"].fillna(0).astype(int)

    # Loại bỏ các cột định danh khỏi features
    drop_cols = {"id","user_id","enrollment_id","lesson_id","skill_id","word_id","created_at","last_practiced", "target_completed"}

    numeric_cols = set(df.select_dtypes(include=["number"]).columns)
    feat_cols = list(numeric_cols - drop_cols)
    
    if not feat_cols:
        logger.warning("No numeric features found. Skipping.")
        return {"status": "skipped_no_features", "version": None}

    Xmat = df[feat_cols]
    y = df["target_completed"]

    logger.info(f"Tổng số mẫu train: {y.shape[0]}")
    logger.info(f"Phân phối lớp (y.value_counts()):\n{y.value_counts(dropna=False)}")

    # =========================================================================
    # [FIX] COLD START CHECK: Kiểm tra dữ liệu có đủ để train không
    # =========================================================================
    
    # 1. Kiểm tra số lượng mẫu tối thiểu
    if len(y) < 5:
        msg = f"Data too small ({len(y)} samples). Need at least 5 samples."
        logger.warning(msg)
        return {
            "status": "skipped_too_small",
            "version": None,
            "val_auc": 0.0,
            "note": msg
        }

    # 2. Kiểm tra số lượng class (Bắt buộc phải có cả 0 và 1)
    if y.nunique() < 2:
        msg = f"Data only has 1 class ({y.unique()}). Model needs at least 2 classes (0 and 1) to learn."
        logger.warning(msg)
        return {
            "status": "skipped_one_class",
            "version": None,
            "val_auc": 0.0,
            "note": msg
        }
    # =========================================================================

    stratify = None
    min_class_count = y.value_counts().min()
    
    # Chỉ stratify nếu class ít nhất có >= 2 mẫu (để chia train/test)
    if min_class_count >= 2:
        stratify = y
            
    try:
        X_train, X_val, y_train, y_val = train_test_split(
            Xmat, y, test_size=0.2, random_state=42, stratify=stratify
        )

        model = GradientBoostingClassifier(
            random_state=42,
            **({"max_depth": params.get("max_depth")} if params.get("max_depth") is not None else {})
        )
        model.fit(X_train, y_train)

        # Eval
        if hasattr(model, "predict_proba"):
            val_pred = model.predict_proba(X_val)[:, 1]
        else:
            import numpy as np
            z = model.decision_function(X_val)
            val_pred = 1 / (1 + np.exp(-z))
            
        # Tính AUC (chỉ tính được nếu tập val có > 1 class)
        if y_val.nunique() > 1:
            auc = float(roc_auc_score(y_val, val_pred))
        else:
            auc = 0.5 # Default neutral score

        if isinstance(auc, float) and math.isnan(auc):
            auc_for_db = None
        else:
            auc_for_db = auc

        # Save Artifact
        payload = {"model": model, "features": feat_cols, "snapshot_id": snapshot_id, "metrics":{"val_auc": auc}}
        artifact_uri = _save_model_artifact(payload, snapshot_id)

        # Update DB Records
        mv, _ = AIModelVersion.objects.get_or_create(
            name="GBM",
            version="latest",
            defaults={"description": "Default GBM holder"},
        )
        real_version = os.path.basename(artifact_uri)
        mv.version = real_version
        mv.description = json.dumps({"val_auc": auc, "snapshot_id": snapshot_id})
        mv.save(update_fields=["version", "description"])

        tr = TrainingRun.objects.create(
            model=mv,
            started_at=timezone.now(),
            finished_at=timezone.now(),
            status="succeeded",
            parameters=params,               
            dataset_snapshot=snapshot_id,    
            metrics={
                "val_auc": auc_for_db,
                "artifact_uri": artifact_uri,
                "features": feat_cols,
                "model_version": real_version,
            }
        )

        return {
            "status": "success",
            "version": real_version,
            "val_auc": auc_for_db,
            "artifact_uri": artifact_uri,
            "features": feat_cols,
            "training_run_id": tr.id,
        }
        
    except Exception as e:
        logger.error(f"Training process failed: {e}")
        raise e