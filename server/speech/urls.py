from django.urls import path
from .views import TextToSpeechView, PronScoreAPIView

urlpatterns = [
    path("speech/tts/", TextToSpeechView.as_view()),
    path("speech/pron/score/", PronScoreAPIView.as_view()),
]