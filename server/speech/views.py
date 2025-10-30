import subprocess
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework import status
import base64
from uuid import uuid4
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from drf_spectacular.utils import extend_schema
import hashlib
from django.utils.timezone import now
from mimetypes import guess_extension

from .serializers import (
    TTSRequestSerializer, TTSResponseSerializer,
    PronScoreRequestSerializer, PronScoreResponseSerializer,
    PronScoreAnySerializer
)
from drf_spectacular.utils import (
    extend_schema, OpenApiExample, OpenApiResponse
)
from .services import tts_synthesize, stt_transcribe, simple_pron_score, stt_transcribe_with_debug


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

        # 1) Sinh audio (base64, mimetype)
        audio_b64, mimetype = tts_synthesize(text, lang)

        # 2) Lưu file vào MEDIA_ROOT/tts/<uuid>.mp3
        filename = f"tts/{uuid4().hex}.mp3"
        content = ContentFile(base64.b64decode(audio_b64))
        saved_path = default_storage.save(filename, content)

        # 3) URL tuyệt đối
        audio_url = request.build_absolute_uri(f"{settings.MEDIA_URL}{saved_path}")

        return Response(
            {"audio_base64": audio_b64, "mime_type": mimetype, "audio_url": audio_url},
            status=status.HTTP_200_OK,
        )


class PronScoreAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        tags=["Speech"],
        summary="Pronunciation Scoring (ASR-based)",
        description=(
            "Gửi `audio_base64` (giọng người học) + `expected_text` (chuỗi mục tiêu). "
            "Server dùng Whisper để nhận dạng và chấm điểm phát âm: điểm tổng 0..100, "
            "kèm điểm từng từ + thời gian ước lượng."
        ),
        request=PronScoreRequestSerializer,
        responses={200: PronScoreResponseSerializer},
    )
    def post(self, request):
        s = PronScoreRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        expected_text = s.validated_data["expected_text"]
        audio_b64 = s.validated_data["audio_base64"]
        lang = s.validated_data.get("lang") or "en"

        # (1) Lấy transcript để trả cho FE (tùy chọn, hữu ích hiển thị “bạn đã nói gì”)
        recognized = stt_transcribe(audio_b64, lang) or ""

        # (2) Chấm điểm bằng hàm đã viết (hàm này tự dùng Whisper nội bộ)
        out = simple_pron_score(audio_b64, expected_text, lang=lang)

        return Response(
            {
                "recognized": recognized,           # text Whisper nghe được
                "score_overall": out["overall"],    # 0..100
                "words": out["words"],              # danh sách từ + score/start/end/status
                "details": out["details"],          # wer/cer/conf/duration/speed_sps
            },
            status=status.HTTP_200_OK,
        )


class PronScoreUpAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    @extend_schema(
        tags=["Speech"],
        summary="Pronunciation Scoring (file hoặc base64)",
        description=(
            "Gửi audio (file hoặc base64) + target_text/expected_text. "
            "Server dùng Whisper để nhận dạng và chấm phát âm (0..100) + điểm từng từ."
        ),
        request=PronScoreAnySerializer,
        responses={200: OpenApiResponse(
            response=PronScoreResponseSerializer,
            description="Kết quả chấm phát âm"
        )},
    )
    def post(self, request):
        s = PronScoreAnySerializer(data=request.data)
        s.is_valid(raise_exception=True)

        expected_text = (s.validated_data.get("target_text")
                         or s.validated_data.get("expected_text")
                         or "").strip()
        lang = s.validated_data.get("language_code") or s.validated_data.get("lang") or "en"

        raw_bytes = None
        src_from = None
        filename = None
        content_type = None

        if "audio" in request.FILES and request.FILES["audio"].size:
            f = request.FILES["audio"]
            filename = getattr(f, "name", None)
            content_type = getattr(f, "content_type", None)
            raw_bytes = f.read()
            src_from = "multipart"
        else:
            # Base64 JSON
            audio_b64 = s.validated_data.get("audio_base64")
            if audio_b64:
                from .services import _b64_to_bytes_any
                raw_bytes = _b64_to_bytes_any(audio_b64)
                src_from = "base64"

        if not raw_bytes:
            return Response({"detail": "Missing audio (file or base64)."}, status=400)

        # Lưu bản thô để so sánh sau
        hexhash = hashlib.sha1(raw_bytes).hexdigest()[:12]
        # Nếu có content_type đoán đuôi; nếu không thì đoán bằng hàm trong services
        ext = None
        if content_type:
            ext = guess_extension(content_type) or ""
        if not ext or ext == ".ksh":  # guess_extension đôi khi trả .ksh với mime lạ
            from .services import _guess_audio_suffix
            ext = _guess_audio_suffix(raw_bytes)
        if not ext.startswith("."):
            ext = f".{ext}" if ext else ".bin"

        rel_path = f"tmp_upload/{hexhash}{ext}"
        default_storage.save(rel_path, ContentFile(raw_bytes))
        file_url = request.build_absolute_uri(f"{settings.MEDIA_URL}{rel_path}")

        # Gọi STT + Score
        try:
            # Dùng pipeline base64 hiện tại cho đồng nhất debug trong services
            audio_b64 = f"data:audio/unknown;base64,{base64.b64encode(raw_bytes).decode()}"
            recognized_text, stt_dbg = stt_transcribe_with_debug(audio_b64, lang)
            out = simple_pron_score(audio_b64, expected_text, lang=lang)

            
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        except subprocess.CalledProcessError as e:
            return Response(
                {"detail": "Failed to decode audio via ffmpeg", "stderr": getattr(e, 'stderr', '')},
                status=400
            )
        except RuntimeError as e:
            # ví dụ "ffmpeg failed to decode audio"
            return Response({"detail": str(e)}, status=400)

        # Gắn block debug upload
        debug_upload = {
            "src": src_from,
            "filename": filename,
            "content_type": content_type,
            "bytes_len": len(raw_bytes),
            "head16": raw_bytes[:16].hex(),
            "saved_path": rel_path,
            "file_url": file_url,
        }

        # Trả kết quả + debug (ffmpeg/probe) từ cả STT & Score
        resp = {
            "recognized": recognized_text,
            "score_overall": out["overall"],
            "words": out["words"],
            "details": out["details"],
            "debug_upload": debug_upload,
            "debug_stt": stt_dbg,              
            "debug_score": out.get("debug"), 
        }
        return Response(resp, status=200)