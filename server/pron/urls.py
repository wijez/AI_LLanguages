from django.urls import path
from .views import PronScoreAPIView

urlpatterns = [
    path('score/', PronScoreAPIView.as_view(), name='pron-score'),
]
