import os
import json, time, hashlib, traceback
from rest_framework import status, permissions
from django.conf import settings
from django.http import JsonResponse
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from ..auth.authentication import BEJWTAuthentication

from ..services.exporter import export_snapshot
from ..ml.trainer import train_from_snapshot
from django.utils import timezone
from django.db import transaction
from ..models import AIModelVersion, TrainingRun
from rest_framework.views import APIView
from rest_framework.response import Response
from typing import Any, Dict
from rest_framework.permissions import IsAuthenticated


class SnapshotIngestJWTView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request):
        return Response({"ok": True})


class TrainView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        payload: Dict[str, Any] = request.data or {}
        snapshot_id = payload.get("snapshot_id")
        params = payload.get("params") or {}

        if not snapshot_id:
            return Response({"detail": "snapshot_id required"}, status=400)

        try:
            # Train and get artifact + metrics
            meta = train_from_snapshot(snapshot_id, params)
            artifact_uri = meta["artifact_uri"]
            features = meta["features"]
            val_auc = meta["val_auc"]

            # Create a model version row
            version_name = os.path.basename(artifact_uri)
            model = AIModelVersion.objects.create(
                name="GBM",
                version=version_name,
                description=json.dumps({"val_auc": val_auc, "snapshot_id": snapshot_id})
            )

            # Create a TrainingRun linked to model (FK REQUIRED by your schema)
            run = TrainingRun.objects.create(
                model=model,
                status="succeeded",
                started_at=timezone.now(),
                finished_at=timezone.now(),
                parameters=params,
                dataset_snapshot=snapshot_id,
                metrics={
                    "val_auc": val_auc,
                    "artifact_uri": artifact_uri,
                    "features": features,
                },
            )

            return Response({"ok": True, "training_run_id": run.id, "metrics": run.metrics}, status=200)

        except Exception as e:
            return Response(
                {"detail": f"train failed: {e}", "trace": traceback.format_exc()[:4000]},
                status=500
            )