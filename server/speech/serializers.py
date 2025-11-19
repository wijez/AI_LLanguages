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


class PronScoreAnySerializer(serializers.Serializer):
    # Cho phép 1 trong 2: audio_base64 (JSON) hoặc audio (file multipart)
    audio_base64 = serializers.CharField(required=False, help_text="data:audio/...;base64,xxx hoặc thuần base64")
    audio = serializers.FileField(required=False, help_text="File audio (wav/mp3/webm/ogg)")

    # Map theo payload swagger bạn vừa gửi
    target_text = serializers.CharField(required=False,allow_blank=True, help_text="= expected_text")
    expected_text = serializers.CharField(required=False,allow_blank=True, help_text="Alias của target_text")
    language_code = serializers.CharField(required=False, help_text="= lang (vd: en, vi)")
    lang = serializers.CharField(required=False, help_text="Alias của language_code")

    def validate(self, attrs):
        if not attrs.get("audio_base64") and not attrs.get("audio"):
            raise serializers.ValidationError("Cần cung cấp audio_base64 (JSON) hoặc audio (file).")
        if not attrs.get("target_text") and not attrs.get("expected_text"):
            raise serializers.ValidationError("Cần target_text hoặc expected_text.")
        return attrs


class PronTTSSampleIn(serializers.Serializer):
    prompt_id = serializers.IntegerField()
    # L2 FE đang lưu trong localStorage.learn, vẫn cho gửi kèm:
    lang = serializers.CharField(required=False, allow_blank=True)