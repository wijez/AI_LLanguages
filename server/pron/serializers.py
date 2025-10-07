from rest_framework import serializers
from .models import TargetUtterance, PronunciationAttempt

class TargetSerializer(serializers.ModelSerializer):
    class Meta:
        model = TargetUtterance
        fields = ['id','text','ipa','language_code']

class PronAttemptSerializer(serializers.ModelSerializer):
    target = TargetSerializer()
    class Meta:
        model = PronunciationAttempt
        fields = [
            'id','target','target_text','language_code','scores','words','suggestions','created_at'
        ]

class PronScoreRequestSerializer(serializers.Serializer):
    # Nhận 1 trong 2: target_id hoặc target_text
    target_id = serializers.IntegerField(required=False)
    target_text = serializers.CharField(required=False, allow_blank=True)
    conversation_id = serializers.UUIDField(required=False)
    language_code = serializers.CharField(required=False, default='en')
    audio = serializers.FileField()

    def validate(self, attrs):
        if not attrs.get('target_id') and not attrs.get('target_text'):
            raise serializers.ValidationError("Cần 'target_id' hoặc 'target_text'.")
        return attrs
