from django.urls import path
from .consumers import LeaderboardConsumer, NotificationConsumer, PracticeLiveConsumer

websocket_urlpatterns = [
    path(r"ws/leaderboard/", LeaderboardConsumer.as_asgi()),
    path(r"ws/notifications/", NotificationConsumer.as_asgi()),
    path(r"ws/practice-live/", PracticeLiveConsumer.as_asgi()),
]
