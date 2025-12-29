from django.urls import re_path
from .consumer import PracticeConsumer

websocket_urlpatterns = [
    re_path(r"ws/practice/$", PracticeConsumer.as_asgi()),
]
