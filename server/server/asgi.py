import os
import django
from django.core.asgi import get_asgi_application
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.settings")
django.setup()
from social.routing import websocket_urlpatterns 



django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,                              # HTTP (DRF, admin, static…)
    "websocket": AuthMiddlewareStack(                     # WebSocket (Channels)
        URLRouter(websocket_urlpatterns)
    ),
})
