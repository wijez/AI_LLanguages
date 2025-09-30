from rest_framework import serializers
from ..models import AIModelVersion


class AIModelVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIModelVersion
        fields = '__all__'


