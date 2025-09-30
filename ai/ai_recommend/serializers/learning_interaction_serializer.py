from rest_framework import serializers
from ..models import LearningInteraction


class LearningInteractionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LearningInteraction
        fields = '__all__'
