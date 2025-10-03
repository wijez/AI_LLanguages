from rest_framework import serializers
from ..models import AIModelVersion, TrainingRun, FeatureSnapshot


class AIModelVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIModelVersion
        fields = '__all__'


class TrainingRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrainingRun
        fields = '__all__'

class FeatureSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeatureSnapshot
        fields = '__all__'

