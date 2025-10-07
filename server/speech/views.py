from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status
import base64
from uuid import uuid4
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from drf_spectacular.utils import extend_schema
from .serializers import (
    TTSRequestSerializer, TTSResponseSerializer,
    PronScoreRequestSerializer, PronScoreResponseSerializer,
)
from .services import tts_synthesize, stt_transcribe, simple_pron_score

class TextToSpeechView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        tags=["Speech"],
        summary="Text-To-Speech",
        description="Nhận text (và lang tùy chọn) → trả audio_base64 (mp3/mpeg) + URL file để nghe.",
        request=TTSRequestSerializer,
        responses={200: TTSResponseSerializer},
    )
    def post(self, request):
        s = TTSRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        text = s.validated_data["text"]
        lang = s.validated_data.get("lang") or "en"

        # 1) Tạo audio (base64, mimetype)
        audio_b64, mimetype = tts_synthesize(text, lang)

        # 2) Lưu ra file trong MEDIA_ROOT/tts/<uuid>.mp3
        filename = f"tts/{uuid4().hex}.mp3"
        content = ContentFile(base64.b64decode(audio_b64))
        saved_path = default_storage.save(filename, content)

        # 3) Tạo URL tuyệt đối để nghe thử
        audio_url = request.build_absolute_uri(f"{settings.MEDIA_URL}{saved_path}")

        # 4) Trả cả base64 + url (tuỳ FE dùng cái nào)
        return Response(
            {
                "audio_base64": audio_b64,
                "mime_type": mimetype,
                "audio_url": audio_url,
            },
            status=200,
        )


class PronScoreAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        tags=["Speech"],
        summary="STT + Pronunciation Scoring",
        description=(
            "Nhận `audio_base64` (giọng người học) và `expected_text` (chuỗi mục tiêu). "
            "Server sẽ STT → `recognized`, sau đó chấm điểm phát âm đơn giản (0..1). "
            "Sau này bạn chỉ cần thay `stt_transcribe` bằng Whisper để có kết quả thật."
        ),
        request=PronScoreRequestSerializer,
        responses={200: PronScoreResponseSerializer},
    )
    def post(self, request):
        s = PronScoreRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        expected = s.validated_data["expected_text"]
        audio_b64 = s.validated_data["audio_base64"]
        lang = s.validated_data.get("lang") or "en"

        recognized = stt_transcribe(audio_b64, lang)
        score, details = simple_pron_score(expected, recognized or "")

        return Response(
            {"recognized": recognized, "score": round(float(score), 4), "details": details},
            status=200
        )
