from django.urls import path
from .consumers import LeaderboardConsumer, NotificationConsumer

websocket_urlpatterns = [
    path(r"ws/leaderboard/", LeaderboardConsumer.as_asgi()),
    path(r"ws/notifications/", NotificationConsumer.as_asgi()),
]
