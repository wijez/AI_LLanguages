import uuid
import time

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.shortcuts import get_object_or_404

from .models import (
    RoleplayScenario,
    RoleplayBlock,
    PracticeSession
)
from .serializers import RoleplayBlockReadSerializer
from .services import (
    save_session,
    get_session,
    ask_gemini_chat,
)
from speech.services_block_tts import generate_tts_from_text


class PracticeConsumer(AsyncJsonWebsocketConsumer):

    async def connect(self):
        await self.accept()

    async def disconnect(self, close_code):
        # Có thể cleanup session nếu muốn
        pass

    # ===============================
    # ROUTER
    # ===============================
    async def receive_json(self, content):
        msg_type = content.get("type")

        if msg_type == "start_practice":
            await self.start_practice(content)

        elif msg_type == "submit_practice":
            await self.submit_practice(content)

        else:
            await self.send_json({
                "type": "error",
                "detail": "Unknown message type"
            })

    # ===============================
    # START PRACTICE
    # ===============================
    async def start_practice(self, data):
        sc_slug = data["scenario"]
        role = data["role"]
        language = data.get("language", "vi")

        scn = (
            RoleplayScenario.objects.filter(slug=sc_slug).first()
            or get_object_or_404(RoleplayScenario, id=sc_slug)
        )

        all_blocks = RoleplayBlock.objects.filter(
            scenario=scn
        ).order_by("order")

        context_blocks = []
        warmup_blocks = []

        for b in all_blocks:
            if b.section == "warmup":
                warmup_blocks.append(b)
            else:
                context_blocks.append(b)

        # ===== SYSTEM CONTEXT =====
        sys_ctx = f"""
Scenario: {scn.title}
Level: {scn.level}
Learner support language: {language}

You are an AI language tutor participating in a roleplay conversation...
"""

        for b in context_blocks:
            sys_ctx += f"\n[{b.section.upper()}]: {b.text}\n"

        # ===== INIT HISTORY =====
        history = []
        ai_greeting_data = None

        if warmup_blocks:
            first = warmup_blocks[0]
            history.append({
                "role": "model",
                "parts": [first.text]
            })
            ai_greeting_data = {
                "text": first.text,
                "audio_key": first.audio_key,
                "role": "assistant"
            }

        sid = str(uuid.uuid4())

        save_session(sid, {
            "mode": "practice",
            "scenario_id": str(scn.id),
            "user_role": role,
            "system_context": sys_ctx,
            "history": history,
            "created_at": int(time.time()),
            "language": language,
        })

        await self.send_json({
            "type": "practice_started",
            "session_id": sid,
            "prologue": [
                RoleplayBlockReadSerializer(b).data
                for b in context_blocks
            ],
            "ai_greeting": ai_greeting_data
        })

    # ===============================
    # SUBMIT PRACTICE
    # ===============================
    async def submit_practice(self, data):
        sid = data["session_id"]
        transcript = data["transcript"]

        sess = get_session(sid)

        if not sess:
            await self.send_json({
                "type": "error",
                "detail": "Invalid session"
            })
            return

        history = sess.get("history", [])
        sys_ctx = sess.get("system_context", "")

        ai_data = ask_gemini_chat(sys_ctx, history, transcript)

        ai_reply = ai_data.get("reply") or "..."
        correction = ai_data.get("corrected")
        explanation = ai_data.get("explanation")

        history.append({"role": "user", "parts": [transcript]})
        history.append({"role": "model", "parts": [ai_reply]})

        sess["history"] = history
        save_session(sid, sess)

        ai_audio = generate_tts_from_text(ai_reply, lang="en")

        await self.send_json({
            "type": "ai_reply",
            "user_transcript": transcript,
            "ai_text": ai_reply,
            "ai_audio": ai_audio,
            "feedback": {
                "has_error": bool(correction),
                "original": transcript,
                "corrected": correction,
                "explanation": explanation
            }
        })
