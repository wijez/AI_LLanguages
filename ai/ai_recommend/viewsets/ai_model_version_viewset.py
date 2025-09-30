from rest_framework import viewsets
from ..models import AIModelVersion
from ..serializers import (
    AIModelVersionSerializer,
)


class AIModelVersionViewSet(viewsets.ModelViewSet):
    queryset = AIModelVersion.objects.all().order_by('-trained_at')
    serializer_class = AIModelVersionSerializer
