from rest_framework import serializers
from progress.models import DailyXP

class DailyXPSerializer(serializers.Serializer):
    class Meta:
        model = DailyXP
        fields = '__all__'