from rest_framework import viewsets
from ..models import LearningInteraction
from ..serializers import (
    LearningInteractionSerializer,
)


class LearningInteractionViewSet(viewsets.ModelViewSet):
    queryset = LearningInteraction.objects.all().order_by('-created_at')
    serializer_class = LearningInteractionSerializer

