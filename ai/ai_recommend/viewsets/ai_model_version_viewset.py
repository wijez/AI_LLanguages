from rest_framework import viewsets, permissions
from ..models import AIModelVersion, TrainingRun, FeatureSnapshot
from ..serializers import AIModelVersionSerializer, TrainingRunSerializer, FeatureSnapshotSerializer

class IsAdmin(permissions.IsAdminUser):
    pass

class AIModelVersionViewSet(viewsets.ModelViewSet):
    queryset = AIModelVersion.objects.all().order_by('-trained_at')
    serializer_class = AIModelVersionSerializer
    # permission_classes = [IsAdmin]

class TrainingRunViewSet(viewsets.ModelViewSet):
    queryset = TrainingRun.objects.all().order_by('-started_at')
    serializer_class = TrainingRunSerializer
    # permission_classes = [IsAdmin]

class FeatureSnapshotViewSet(viewsets.ModelViewSet):
    queryset = FeatureSnapshot.objects.all().order_by('-created_at')
    serializer_class = FeatureSnapshotSerializer
    # permission_classes = [IsAdmin]
