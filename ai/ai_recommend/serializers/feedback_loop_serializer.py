from rest_framework import serializers
from ..models import FeedbackLoop


class FeedbackLoopSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeedbackLoop
        fields = '__all__'
