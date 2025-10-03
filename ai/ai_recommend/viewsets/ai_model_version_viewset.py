from rest_framework import viewsets
from ..models import AIModelVersion, TrainingRun, FeatureSnapshot
from ..serializers import (
    AIModelVersionSerializer,
    TrainingRunSerializer,
    FeatureSnapshotSerializer,
)


class AIModelVersionViewSet(viewsets.ModelViewSet):
    queryset = AIModelVersion.objects.all().order_by('-trained_at')
    serializer_class = AIModelVersionSerializer


class TrainingRunViewSet(viewsets.ModelViewSet):
    queryset = TrainingRun.objects.all().order_by('-started_at')
    serializer_class = TrainingRunSerializer


class FeatureSnapshotViewSet(viewsets.ModelViewSet):
    queryset = FeatureSnapshot.objects.all().order_by('-created_at')
    serializer_class = FeatureSnapshotSerializer
