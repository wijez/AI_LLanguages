from rest_framework import viewsets
from ..models import FeedbackLoop
from ..serializers import (
    FeedbackLoopSerializer,
)


class FeedbackLoopViewSet(viewsets.ModelViewSet):
    queryset = FeedbackLoop.objects.all()
    serializer_class = FeedbackLoopSerializer
