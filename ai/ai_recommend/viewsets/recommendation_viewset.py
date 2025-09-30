from rest_framework import viewsets
from ..models import Recommendation
from ..serializers import (
    RecommendationSerializer,
)


class RecommendationViewSet(viewsets.ModelViewSet):
    queryset = Recommendation.objects.all().order_by('-created_at')
    serializer_class = RecommendationSerializer
