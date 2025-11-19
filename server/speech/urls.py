from django.urls import path
from .views import TextToSpeechView, PronScoreAPIView, PronScoreUpAPIView, PronunciationTTSSampleView

urlpatterns = [
    path("speech/tts/", TextToSpeechView.as_view()),
    path("speech/pron/score/", PronScoreAPIView.as_view()),
    path("speech/pron/up/" ,PronScoreUpAPIView.as_view()),
    path("speech/pron/tts/", PronunciationTTSSampleView.as_view(), name="pron-tts"),
]