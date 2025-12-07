import os
import subprocess
from django.db.models.base import transaction
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

from languages.models import LanguageEnrollment, PronunciationPrompt, Skill
from learning.models import PronAttempt, SkillSession

from .serializers import (
    TTSRequestSerializer, TTSResponseSerializer,
    PronScoreRequestSerializer, PronScoreResponseSerializer,
    PronScoreAnySerializer, PronTTSSampleIn
)
from drf_spectacular.utils import (
    extend_schema, OpenApiExample, OpenApiResponse
)
from .services import tts_synthesize, stt_transcribe, simple_pron_score, stt_transcribe_with_debug,  _ffprobe_json, _probe_duration_sec

def _tts_cache_key(text: str) -> str:
    # chỉ 1 ngôn ngữ, nên hash theo text đã chuẩn hóa (strip + nén khoảng trắng)
    norm = " ".join((text or "").strip().split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


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
        # audio_b64, mimetype = tts_synthesize(text, lang)
        try:
            audio_b64, mimetype = tts_synthesize(text, lang)
        except Exception as e:
            return Response(
                {
                    "detail": "TTS provider failed",
                    "hint": "Ưu tiên cài Piper + voice; nếu không có, đảm bảo mạng khi dùng gTTS.",
                    "error": str(e),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # 2) Lưu file vào MEDIA_ROOT/tts/<uuid>.mp3
        hexhash = hashlib.sha1(f"{lang}|{text}".encode("utf-8")).hexdigest()[:20]
        # filename = f"tts/{uuid4().hex}.mp3"
        filename = f"tts/{lang}/{hexhash}.mp3"

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


# class PronScoreUpAPIView(APIView):
#     permission_classes = [AllowAny]
#     authentication_classes = []
#     parser_classes = [JSONParser, MultiPartParser, FormParser]

#     @extend_schema(
#         tags=["Speech"],
#         summary="Pronunciation Scoring (file hoặc base64)",
#         description=(
#             "Gửi audio (file hoặc base64) + target_text/expected_text. "
#             "Server dùng Whisper để nhận dạng và chấm phát âm (0..100) + điểm từng từ."
#         ),
#         request=PronScoreAnySerializer,
#         responses={200: OpenApiResponse(
#             response=PronScoreResponseSerializer,
#             description="Kết quả chấm phát âm"
#         )},
#     )
#     def post(self, request):
#         s = PronScoreAnySerializer(data=request.data)
#         s.is_valid(raise_exception=True)

#         expected_text = (s.validated_data.get("target_text")
#                          or s.validated_data.get("expected_text")
#                          or "").strip()
#         lang = s.validated_data.get("language_code") or s.validated_data.get("lang") or "en"

#         raw_bytes = None
#         src_from = None
#         filename = None
#         content_type = None

#         if "audio" in request.FILES and request.FILES["audio"].size:
#             f = request.FILES["audio"]
#             filename = getattr(f, "name", None)
#             content_type = getattr(f, "content_type", None)
#             raw_bytes = f.read()
#             src_from = "multipart"
#         else:
#             # Base64 JSON
#             audio_b64 = s.validated_data.get("audio_base64")
#             if audio_b64:
#                 from .services import _b64_to_bytes_any
#                 raw_bytes = _b64_to_bytes_any(audio_b64)
#                 src_from = "base64"

#         if not raw_bytes:
#             return Response({"detail": "Missing audio (file or base64)."}, status=400)

#         # Lưu bản thô để so sánh sau
#         hexhash = hashlib.sha1(raw_bytes).hexdigest()[:12]
#         # Nếu có content_type đoán đuôi; nếu không thì đoán bằng hàm trong services
#         ext = None
#         if content_type:
#             ext = guess_extension(content_type) or ""
#         if not ext or ext == ".ksh":  # guess_extension đôi khi trả .ksh với mime lạ
#             from .services import _guess_audio_suffix
#             ext = _guess_audio_suffix(raw_bytes)
#         if not ext.startswith("."):
#             ext = f".{ext}" if ext else ".bin"

#         rel_path = f"tmp_upload/{hexhash}{ext}"
#         default_storage.save(rel_path, ContentFile(raw_bytes))
#         file_url = request.build_absolute_uri(f"{settings.MEDIA_URL}{rel_path}")

#         # Gọi STT + Score
#         try:
#             # Dùng pipeline base64 hiện tại cho đồng nhất debug trong services
#             audio_b64 = f"data:audio/unknown;base64,{base64.b64encode(raw_bytes).decode()}"
#             # recognized_text, stt_dbg = stt_transcribe_with_debug(audio_b64, lang)
#             out = simple_pron_score(audio_b64, expected_text, lang=lang)

            
#         except ValueError as e:
#             return Response({"detail": str(e)}, status=400)
#         except subprocess.CalledProcessError as e:
#             return Response(
#                 {"detail": "Failed to decode audio via ffmpeg", "stderr": getattr(e, 'stderr', '')},
#                 status=400
#             )
#         except RuntimeError as e:
#             # ví dụ "ffmpeg failed to decode audio"
#             return Response({"detail": str(e)}, status=400)

#         # Gắn block debug upload
#         debug_upload = {
#             "src": src_from,
#             "filename": filename,
#             "content_type": content_type,
#             "bytes_len": len(raw_bytes),
#             "head16": raw_bytes[:16].hex(),
#             "saved_path": rel_path,
#             "file_url": file_url,
#         }
#         # === GHI LỊCH SỬ PronAttempt (chỉ khi user đã xác thực) ===
#         if request.user and request.user.is_authenticated:
#             session_obj = None

#             # 1) Ưu tiên: nhận skill_session (PK id, int) từ client
#             raw_sid = request.data.get("skill_session")
#             if raw_sid is not None:
#                 try:
#                     sid = int(str(raw_sid).strip())
#                 except (ValueError, TypeError):
#                     return Response({"detail": "skill_session phải là số nguyên (id)."}, status=400)

#                 session_obj = SkillSession.objects.filter(id=sid, user=request.user).first()
#                 if session_obj is None:
#                     return Response({"detail": "Không tìm thấy phiên hoặc không thuộc bạn."}, status=404)

#             # 2) Fallback: nếu không gửi skill_session, cho phép auto-create khi có skill_id + enrollment_id
#             if session_obj is None:
#                 skill_id = request.data.get("skill_id")
#                 enrollment_id = request.data.get("enrollment_id")
#                 lesson_id = request.data.get("lesson_id")  # optional

#                 if skill_id and enrollment_id:
#                     try:
#                         skill = Skill.objects.get(pk=int(skill_id))
#                         enrollment = LanguageEnrollment.objects.get(pk=int(enrollment_id), user=request.user)
#                     except (ValueError, Skill.DoesNotExist, LanguageEnrollment.DoesNotExist):
#                         return Response({"detail": "skill_id hoặc enrollment_id không hợp lệ."}, status=400)

#                     # Kiểm tra cùng ngôn ngữ
#                     lang_abbr = getattr(enrollment.language, "abbreviation", "").lower()
#                     if (skill.language_code or "").lower() != lang_abbr:
#                         return Response({"detail": "Enrollment và Skill không cùng ngôn ngữ."}, status=400)

#                     session_obj = SkillSession.objects.create(
#                         user=request.user,
#                         enrollment=enrollment,
#                         skill=skill,
#                         lesson_id=int(lesson_id) if lesson_id else None,
#                         status="in_progress",
#                         meta={"source": "pron_up_autostart"},
#                     )
#                 else:
#                     return Response(
#                         {"detail": "Cần truyền skill_session (id) hoặc skill_id + enrollment_id để tạo mới."},
#                         status=400,
#                     )

#             # 3) Ghi attempt
#             prompt_obj = None
#             prompt_id = request.data.get("prompt_id")
#             if prompt_id:
#                 try:
#                     prompt_obj = PronunciationPrompt.objects.get(pk=int(prompt_id), skill=session_obj.skill)
#                 except Exception:
#                     prompt_obj = None

#             PronAttempt.objects.create(
#                 session=session_obj,
#                 prompt_id=prompt_obj,
#                 expected_text=expected_text,
#                 # recognized=recognized_text,
#                 score_overall=float(out["overall"]),
#                 words=out["words"],
#                 details=out["details"],
#                 audio_path=rel_path,  # MEDIA relative path
#             )

#             # cập nhật stats nhanh cho session
#             session_obj._recalc_scores()
#             session_obj.last_activity = now()
#             session_obj.save(update_fields=["attempts_count", "best_score", "avg_score", "last_activity"])
#         # Trả kết quả + debug (ffmpeg/probe) từ cả STT & Score
#         resp = {
#             # "recognized": recognized_text,
#             "score_overall": out["overall"],
#             "words": out["words"],
#             "details": out["details"],
#             "debug_upload": debug_upload,
#             # "debug_stt": stt_dbg,              
#             "debug_score": out.get("debug"), 
#         }
#         return Response(resp, status=200)
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

        expected_text = (
            s.validated_data.get("target_text")
            or s.validated_data.get("expected_text")
            or ""
        ).strip()
        lang = (
            s.validated_data.get("language_code")
            or s.validated_data.get("lang")
            or "en"
        )

        raw_bytes = None
        src_from = None
        filename = None
        content_type = None

        # 1) Lấy raw_bytes từ file multipart hoặc base64 JSON
        if "audio" in request.FILES and request.FILES["audio"].size:
            f = request.FILES["audio"]
            filename = getattr(f, "name", None)
            content_type = getattr(f, "content_type", None)
            raw_bytes = f.read()
            src_from = "multipart"
        else:
            audio_b64 = s.validated_data.get("audio_base64")
            if audio_b64:
                from .services import _b64_to_bytes_any
                raw_bytes = _b64_to_bytes_any(audio_b64)
                src_from = "base64"

        if not raw_bytes:
            return Response({"detail": "Missing audio (file or base64)."}, status=400)

        # 2) Lưu bản thô vào MEDIA để debug / xem lại
        hexhash = hashlib.sha1(raw_bytes).hexdigest()[:12]

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

        # 3) Gọi 1 pipeline duy nhất: Whisper + scoring
        try:
            # data URL để tái sử dụng pipeline có sẵn trong services
            audio_b64 = f"data:audio/unknown;base64,{base64.b64encode(raw_bytes).decode()}"
            out = simple_pron_score(audio_b64, expected_text, lang=lang)

        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        except subprocess.CalledProcessError as e:
            return Response(
                {
                    "detail": "Failed to decode audio via ffmpeg",
                    "stderr": getattr(e, "stderr", ""),
                },
                status=400,
            )
        except RuntimeError as e:
            # ví dụ "ffmpeg failed to decode audio"
            return Response({"detail": str(e)}, status=400)

        # 4) Lấy recognized từ kết quả scoring (không gọi STT lần 2)
        details = out.get("details") or {}
        recognized_text = details.get("recognized", "")

        debug_upload = {
            "src": src_from,
            "filename": filename,
            "content_type": content_type,
            "bytes_len": len(raw_bytes),
            "head16": raw_bytes[:16].hex(),
            "saved_path": rel_path,
            "file_url": file_url,
        }

        # 5) Ghi lịch sử PronAttempt (chỉ khi user đã xác thực)
        if request.user and request.user.is_authenticated:
            session_obj = None

            # 5.1) Ưu tiên: nhận skill_session (PK id, int) từ client
            raw_sid = request.data.get("skill_session")
            if raw_sid is not None:
                try:
                    sid = int(str(raw_sid).strip())
                except (ValueError, TypeError):
                    return Response(
                        {"detail": "skill_session phải là số nguyên (id)."},
                        status=400,
                    )

                session_obj = SkillSession.objects.filter(
                    id=sid, user=request.user
                ).first()
                if session_obj is None:
                    return Response(
                        {"detail": "Không tìm thấy phiên hoặc không thuộc bạn."},
                        status=404,
                    )

            # 5.2) Fallback: nếu không gửi skill_session, auto-create khi có skill_id + enrollment_id
            if session_obj is None:
                skill_id = request.data.get("skill_id")
                enrollment_id = request.data.get("enrollment_id")
                lesson_id = request.data.get("lesson_id")  # optional

                if skill_id and enrollment_id:
                    try:
                        skill = Skill.objects.get(pk=int(skill_id))
                        enrollment = LanguageEnrollment.objects.get(
                            pk=int(enrollment_id), user=request.user
                        )
                    except (ValueError, Skill.DoesNotExist, LanguageEnrollment.DoesNotExist):
                        return Response(
                            {"detail": "skill_id hoặc enrollment_id không hợp lệ."},
                            status=400,
                        )

                    # Kiểm tra cùng ngôn ngữ
                    lang_abbr = getattr(enrollment.language, "abbreviation", "").lower()
                    if (skill.language_code or "").lower() != lang_abbr:
                        return Response(
                            {"detail": "Enrollment và Skill không cùng ngôn ngữ."},
                            status=400,
                        )

                    session_obj = SkillSession.objects.create(
                        user=request.user,
                        enrollment=enrollment,
                        skill=skill,
                        lesson_id=int(lesson_id) if lesson_id else None,
                        status="in_progress",
                        meta={"source": "pron_up_autostart"},
                    )
                else:
                    return Response(
                        {
                            "detail": (
                                "Cần truyền skill_session (id) hoặc "
                                "skill_id + enrollment_id để tạo mới."
                            )
                        },
                        status=400,
                    )

            # 5.3) Ghi attempt
            prompt_obj = None
            prompt_id = request.data.get("prompt_id")
            if prompt_id:
                try:
                    prompt_obj = PronunciationPrompt.objects.get(
                        pk=int(prompt_id), skill=session_obj.skill
                    )
                except Exception:
                    prompt_obj = None

            PronAttempt.objects.create(
                session=session_obj,
                prompt_id=prompt_obj,
                expected_text=expected_text,
                recognized=recognized_text,
                score_overall=float(out["overall"]),
                words=out["words"],
                details=details,
                audio_path=rel_path,  # MEDIA relative path
            )

            # cập nhật stats nhanh cho session
            session_obj._recalc_scores()
            session_obj.last_activity = now()
            session_obj.save(
                update_fields=[
                    "attempts_count",
                    "best_score",
                    "avg_score",
                    "last_activity",
                ]
            )

        # 6) Trả kết quả (1 pass Whisper) + debug
        resp = {
            "recognized": recognized_text,
            "score_overall": out["overall"],
            "words": out["words"],
            "details": details,
            "debug_upload": debug_upload,
            # giữ debug_score; nếu simple_pron_score trả thêm debug nội bộ
            "debug_score": out.get("debug"),
        }
        return Response(resp, status=200)


class PronunciationTTSSampleView(APIView):
    """
    POST /api/speech/pron/tts/
    Body: { "prompt_id": <id>, "lang": "vi|en|zh" (optional) }

    Lần đầu: synth + lưu file vào prompt.tts_file
    Lần sau: trả file đã cache (không synth lại)
    """
    permission_classes = [AllowAny]

    def post(self, request):
        s = PronTTSSampleIn(data=request.data)
        s.is_valid(raise_exception=True)

        prompt_id = s.validated_data["prompt_id"]
        lang = (s.validated_data.get("lang") or "en").lower().strip()

        with transaction.atomic():
            try:
                prompt = (
                    PronunciationPrompt.objects
                    .select_for_update()
                    .get(id=prompt_id)
                )
            except PronunciationPrompt.DoesNotExist:
                return Response({"detail": "prompt_not_found"}, status=status.HTTP_400_BAD_REQUEST)

            # Text để đọc (ưu tiên answer, fallback word)
            text = (prompt.answer or prompt.word or "").strip()
            if not text:
                return Response({"detail": "empty_prompt_text"}, status=status.HTTP_400_BAD_REQUEST)

            tkey = _tts_cache_key(text)

            # ==== 1) CACHE HIT (và file còn tồn tại) ====
            storage = prompt.tts_file.storage if prompt.tts_file else None
            cached_ok = False
            if prompt.tts_file and prompt.tts_hash == tkey and storage:
                try:
                    cached_ok = storage.exists(prompt.tts_file.name)
                except Exception:
                    cached_ok = False

            if cached_ok:
                # absolute URL để FE dùng trực tiếp
                abs_url = request.build_absolute_uri(prompt.tts_file.url)

                # (tuỳ chọn) kèm base64: FE có thể ưu tiên URL, fallback base64
                b64 = None
                try:
                    with storage.open(prompt.tts_file.name, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode("utf-8")
                except Exception:
                    pass

                return Response({
                    "cached": True,
                    "mimetype": prompt.tts_mime,
                    "audio_base64": b64,
                    "url": abs_url,
                    "duration": prompt.tts_duration,
                    "provider": prompt.tts_provider,
                })

            # ==== 2) CACHE MISS → synth (Piper trước, gTTS fallback trong services) ====
            audio_b64, mimetype = tts_synthesize(text, lang)

            # Thư mục & file đích
            rel_dir = os.path.join("tts", "pron", f"{prompt.id % 100:02d}")
            abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
            os.makedirs(abs_dir, exist_ok=True)

            rel_filename = f"{prompt.id}-{tkey}.mp3"
            rel_path_fs = os.path.join(rel_dir, rel_filename)        # path FS (có thể có '\')
            abs_path = os.path.join(settings.MEDIA_ROOT, rel_path_fs)

            # Ghi file
            with open(abs_path, "wb") as f:
                f.write(base64.b64decode(audio_b64))

            # Lấy duration (optional)
            try:
                meta = _ffprobe_json(abs_path)
                duration = float(_probe_duration_sec(meta) or 0.0)
            except Exception:
                duration = 0.0

            # Ghi vào model: name dùng forward-slash để URL luôn đúng trên Windows
            rel_path_url = rel_path_fs.replace(os.sep, "/")
            prompt.tts_file.name = rel_path_url
            prompt.tts_mime = mimetype
            prompt.tts_hash = tkey
            prompt.tts_duration = duration
            prompt.tts_provider = "piper"
            prompt.save(update_fields=["tts_file", "tts_mime", "tts_hash", "tts_duration", "tts_provider"])

        # Build absolute URL từ FileField.url (chuẩn nhất)
        abs_url = request.build_absolute_uri(prompt.tts_file.url)

        return Response({
            "cached": False,
            "mimetype": mimetype,
            "audio_base64": audio_b64,   # cho phát ngay lần đầu
            "url": abs_url,              # FE nên ưu tiên dùng URL (đã cache)
            "duration": duration,
            "provider": "piper",
        })