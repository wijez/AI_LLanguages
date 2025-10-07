from rest_framework import serializers

# ----- TTS -----
class TTSRequestSerializer(serializers.Serializer):
    text = serializers.CharField()
    lang = serializers.CharField(required=False, allow_blank=True)  # ví dụ: 'en', 'vi'

class TTSResponseSerializer(serializers.Serializer):
    audio_base64 = serializers.CharField()
    mime_type = serializers.CharField(default="audio/mpeg")

# ----- STT + Pron score -----
class PronScoreRequestSerializer(serializers.Serializer):
    expected_text = serializers.CharField()
    audio_base64 = serializers.CharField()  # base64 của file ghi âm (wav/mp3/m4a)
    lang = serializers.CharField(required=False, allow_blank=True)

class PronScoreResponseSerializer(serializers.Serializer):
    recognized = serializers.CharField()     # text nhận dạng được
    score = serializers.FloatField()         # 0.0 ~ 1.0
    details = serializers.DictField()        # các chỉ số phụ (tùy bạn mở rộng)
    