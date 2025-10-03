from rest_framework import viewsets
from ..models import Recommendation
from ..serializers import (
    RecommendationSerializer,
)


class RecommendationViewSet(viewsets.ModelViewSet):
    queryset = Recommendation.objects.all().order_by('-created_at')
    serializer_class = RecommendationSerializer
    def get_queryset(self):
        user_id =  self.request.user.id
        return Recommendation.objects.filter(user_id=user_id).order_by('-priority_score')