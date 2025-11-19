from django.urls import re_path
from .consumers import LeaderboardConsumer

websocket_urlpatterns = [
    re_path(r"ws/leaderboard/$", LeaderboardConsumer.as_asgi()),
]
