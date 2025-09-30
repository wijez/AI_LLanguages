from rest_framework import viewsets
from ..models import FeedbackLoop
from ..serializers import (
    FeedbackLoopSerializer,
)


class FeedbackLoopViewSet(viewsets.ModelViewSet):
    queryset = FeedbackLoop.objects.all().order_by('-created_at')
    serializer_class = FeedbackLoopSerializer
