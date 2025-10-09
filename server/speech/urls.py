from django.urls import path
from .views import TextToSpeechView, PronScoreAPIView, PronScoreUpAPIView

urlpatterns = [
    path("speech/tts/", TextToSpeechView.as_view()),
    path("speech/pron/score/", PronScoreAPIView.as_view()),
    path("speech/pron/up/" ,PronScoreUpAPIView.as_view()),
]