import os
import django
from django.core.asgi import get_asgi_application
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.settings")
django.setup()
from social.middleware import RequestIDWebSocketMiddleware, JWTAuthMiddleware
from social.routing import websocket_urlpatterns
from languages.routing import websocket_urlpatterns as ls


websocket_urlpatterns += ls
django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,                              # HTTP (DRF, admin, static…)
   "websocket": AllowedHostsOriginValidator(
        # RequestID -> JWTAuth -> AuthStack -> Router
        RequestIDWebSocketMiddleware(
            JWTAuthMiddleware(
                AuthMiddlewareStack(
                    URLRouter(websocket_urlpatterns),
                )
            )
        )
    ),
})

