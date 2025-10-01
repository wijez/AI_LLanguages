from rest_framework import serializers
from ..models import LearningInteraction
from .mistake_serializer import MistakeSerializer 
from .recommendation_serializer import RecommendationSerializer 


class LearningInteractionSerializer(serializers.ModelSerializer):
    mistakes = MistakeSerializer(many=True, read_only=True)
    recommendations = RecommendationSerializer(many=True, read_only=True)
    class Meta:
        model = LearningInteraction
        fields = '__all__'
