from uuid import uuid4
from urllib.parse import parse_qs
from utils.config_log import request_id_ctx

class RequestIDWebSocketMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # ưu tiên header, fallback query, fallback generate
        headers = dict(scope.get("headers", []))
        rid = (
            headers.get(b"x-request-id", b"").decode()
            or parse_qs(scope.get("query_string", b"").decode()).get("rid", [None])[0]
            or uuid4().hex[:12]
        )

        token = request_id_ctx.set(rid)
        scope["request_id"] = rid

        try:
            return await self.app(scope, receive, send)
        finally:
            request_id_ctx.reset(token)


from urllib.parse import parse_qs
from django.contrib.auth.models import AnonymousUser
from channels.middleware import BaseMiddleware
from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth import get_user_model

User = get_user_model()

class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        scope["user"] = AnonymousUser()

        token = None

        qs = parse_qs(scope.get("query_string", b"").decode())
        if "token" in qs:
            token = qs["token"][0]

        if not token:
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization")
            if auth:
                try:
                    prefix, token = auth.decode().split()
                    if prefix.lower() != "bearer":
                        token = None
                except ValueError:
                    token = None

        if token:
            try:
                validated = AccessToken(token)
                user_id = validated["user_id"]
                scope["user"] = await User.objects.aget(id=user_id)
            except Exception:
                scope["user"] = AnonymousUser()

        return await super().__call__(scope, receive, send)
