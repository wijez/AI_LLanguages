# ai/ai_recommend/viewsets/predict.py
from __future__ import annotations

import io
import json
import joblib
import pandas as pd
from typing import List, Dict, Any
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from ..models import TrainingRun  
from rest_framework.permissions import IsAuthenticated


# S3/MinIO đọc qua s3fs nếu artifact_uri/features_uri là s3://...
def _read_parquet(uri: str) -> pd.DataFrame:
    if uri.startswith("s3://"):
        import s3fs 
        fs = s3fs.S3FileSystem(
            client_kwargs={
                "endpoint_url": getattr(settings, "MINIO_ENDPOINT", None)
            },
            key=getattr(settings, "MINIO_ACCESS_KEY", None),
            secret=getattr(settings, "MINIO_SECRET_KEY", None)
        )
        with fs.open(uri.replace("s3://", ""), "rb") as f:
            return pd.read_parquet(f)
    else:
        return pd.read_parquet(uri)

def _open_binary(uri: str):
    """Trả về bytes của model artifact (joblib.pkl)."""
    if uri.startswith("s3://"):
        import s3fs
        fs = s3fs.S3FileSystem(
            client_kwargs={
                "endpoint_url": getattr(settings, "MINIO_ENDPOINT", None)
            },
            key=getattr(settings, "MINIO_ACCESS_KEY", None),
            secret=getattr(settings, "MINIO_SECRET_KEY", None)
        )
        with fs.open(uri.replace("s3://", ""), "rb") as f:
            return f.read()
    else:
        with open(uri, "rb") as f:
            return f.read()

def _load_latest_model():
    tr = TrainingRun.objects.filter(status="succeeded").order_by("-started_at").first()
    if not tr or not tr.metrics:
        return None, "No succeeded TrainingRun with metrics found."
    artifact_uri = tr.metrics.get("artifact_uri")
    if not artifact_uri:
        return None, "TrainingRun.metrics['artifact_uri'] not set."
    blob = _open_binary(artifact_uri)
    model = joblib.load(io.BytesIO(blob))
    return model, None

class PredictView(APIView):
    permission_classes = [IsAuthenticated]
    """
    POST /api/predict
    {
      "snapshot_id": "2025-10-10-test",
      "features_uri": "s3://ai-snapshots/snapshots/2025-10-10-test/features.parquet",  # optional, nếu không có sẽ tự build từ snapshot_id
      "enrollment_ids": [1,2,3],  # optional -> nếu bỏ trống sẽ predict tất cả hàng
      "top_k": 100  # optional -> server vẫn trả đầy đủ, client có thể cắt
    }
    """
    def post(self, request, *args, **kwargs):
        payload = request.data or {}
        snapshot_id = payload.get("snapshot_id")
        features_uri = payload.get("features_uri")
        enrollment_ids = payload.get("enrollment_ids")  # list[int] optional


        if not features_uri:
            if not snapshot_id:
                return Response({"detail": "Provide snapshot_id or features_uri"}, status=400)
            # build uri mặc định theo exporters.py
            bucket = getattr(settings, "MINIO_BUCKET", "ai-snapshots")
            prefix = f"snapshots/{snapshot_id}"
            features_uri = f"s3://{bucket}/{prefix}/features.parquet"

        # load model
        model, err = _load_latest_model()
        if err:
            return Response({"detail": err}, status=503)

        # load features
        try:
            df = _read_parquet(features_uri)
        except Exception as e:
            return Response({"detail": f"Cannot read features: {e}"}, status=500)

        # lọc enrollment
        if enrollment_ids:
            df = df[df["enrollment_id"].isin(enrollment_ids)]

        if df.empty:
            return Response({"predictions": []})

        # chuẩn hoá feature matrix
        drop_cols = [c for c in ["id","user_id","enrollment_id","created_at"] if c in df.columns]
        X = df.drop(columns=drop_cols, errors="ignore").copy()
        X = X.fillna(0)

        # predict proba/score
        try:
            if hasattr(model, "predict_proba"):
                p = model.predict_proba(X)[:, 1]
            else:
                # e.g., linear SVM: decision_function -> map to 0..1 bằng sigmoid
                import numpy as np
                z = model.decision_function(X)
                p = 1 / (1 + np.exp(-z))
        except Exception as e:
            return Response({"detail": f"Predict error: {e}"}, status=500)

        out = []
        for enr, prob in zip(df["enrollment_id"].tolist(), p.tolist()):
            out.append({"enrollment_id": int(enr), "p_hat": float(prob)})

        return Response({"predictions": out}, status=200)
