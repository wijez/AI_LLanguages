from channels.generic.websocket import AsyncJsonWebsocketConsumer

class LeaderboardConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        await self.channel_layer.group_add("lb.all", self.channel_name)           
        if user and user.is_authenticated:
            await self.channel_layer.group_add(f"lb.friends.{user.id}", self.channel_name) 
        await self.accept()

    async def disconnect(self, code):
        user = self.scope.get("user")
        await self.channel_layer.group_discard("lb.all", self.channel_name)
        if user and user.is_authenticated:
            await self.channel_layer.group_discard(f"lb.friends.{user.id}", self.channel_name)  


    async def lb_changed_all(self, event):
        await self.send_json({"type": "lb_changed_all"})

    async def lb_changed_friends(self, event):
        await self.send_json({"type": "lb_changed_friends"})


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        
        if not user or not user.is_authenticated:
            await self.close(code=4003) 
            return
        
        self.group_name = f"user_{user.id}"
    
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )

    async def notify(self, event):
        await self.send_json(event["data"])


import json
import asyncio
import os
import base64
import logging
from urllib.parse import parse_qs
from channels.generic.websocket import AsyncWebsocketConsumer
from google import genai
from languages.models import RoleplayScenario

logger = logging.getLogger(__name__)

class PracticeLiveConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # 1. Lấy thông tin Scenario từ query string
        query_string = self.scope.get("query_string", b"").decode()
        params = parse_qs(query_string)
        scenario_slug = params.get("scenario", [None])[0]
        self.role = params.get("role", ["student"])[0]

        if not scenario_slug:
            await self.close(code=4000)
            return

        # 2. Load Context
        try:
            scenario = await RoleplayScenario.objects.aget(slug=scenario_slug)
            blocks = []
            async for b in scenario.blocks.order_by("order"):
                blocks.append(f"[{b.section}] {b.role or 'System'}: {b.text}")
            
            context_text = "\n".join(blocks)
        except RoleplayScenario.DoesNotExist:
            await self.close(code=4004)
            return

        # 3. Chấp nhận kết nối WS
        await self.accept()

        # 4. Khởi tạo Gemini Live Client
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            # SỬA: Dùng json.dumps + send thay vì send_json
            await self.send(text_data=json.dumps({"error": "Missing API Key"}))
            await self.close()
            return

        self.client = genai.Client(api_key=api_key)
        self.model_id = "gemini-2.5-flash-tts" 

        sys_instr = (
            f"You are a helpful English tutor acting in a roleplay scenario.\n"
            f"CONTEXT:\n{context_text}\n\n"
            f"YOUR ROLE: Interact naturally with the student (role: {self.role}).\n"
            f"INSTRUCTIONS:\n"
            f"- Listen to the student's audio input directly.\n"
            f"- Respond with natural voice (audio).\n"
            f"- Keep responses concise and conversational."
        )

        try:
            # 5. Kết nối tới Gemini Live Session
            self.live_ctx = self.client.aio.live.connect(
                model=self.model_id,
                config={
                    "system_instruction": sys_instr,
                    "response_modalities": ["AUDIO"] 
                }
            )
            # Vào context thủ công
            self.live_session = await self.live_ctx.__aenter__()

            # 6. Chạy background task
            self.receive_task = asyncio.create_task(self.proxy_gemini_to_client())
            
            # SỬA: send_json -> send(json.dumps)
            await self.send(text_data=json.dumps({"type": "status", "msg": "connected"}))
            
        except Exception as e:
            logger.error(f"Gemini Connect Error: {e}")
            # SỬA: send_json -> send(json.dumps) để tránh crash Attribute Error
            error_msg = str(e)
            if "quota" in error_msg.lower():
                error_msg = "Google API Quota Exceeded. Please check billing."
            
            await self.send(text_data=json.dumps({"type": "error", "msg": error_msg}))
            await self.close()

    async def disconnect(self, close_code):
        if hasattr(self, 'receive_task'):
            self.receive_task.cancel()
            try:
                await self.receive_task
            except asyncio.CancelledError:
                pass

        if hasattr(self, 'live_ctx'):
            # Thoát context thủ công, cẩn thận bắt lỗi nếu kết nối đã chết
            try:
                await self.live_ctx.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error closing Gemini context: {e}")

    async def receive(self, text_data=None, bytes_data=None):
        try:
            if text_data:
                data = json.loads(text_data)
                
                if hasattr(self, 'live_session'):
                    if "audio_data" in data:
                        await self.live_session.send(
                            input={"data": data["audio_data"], "mime_type": "audio/pcm"}, 
                            end_of_turn=False
                        )
                    elif "commit" in data:
                        await self.live_session.send(input="", end_of_turn=True)

        except Exception as e:
            logger.error(f"Error in receive: {e}")

    async def proxy_gemini_to_client(self):
        try:
            async for response in self.live_session.receive():
                if response.data:
                    b64_audio = base64.b64encode(response.data).decode("utf-8")
                    # SỬA: send_json -> send
                    await self.send(text_data=json.dumps({
                        "type": "audio",
                        "data": b64_audio
                    }))
                
                if response.text:
                    # SỬA: send_json -> send
                    await self.send(text_data=json.dumps({
                        "type": "text",
                        "content": response.text
                    }))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Gemini proxy error: {e}")
            # await self.send(text_data=json.dumps({"type": "error", "msg": str(e)}))