from rest_framework import routers
from django.urls import path, include
from .viewsets import (
    AIModelVersionViewSet,
    RecommendationViewSet,
    FeedbackLoopViewSet,
    FeatureSnapshotViewSet,
    TrainingRunViewSet,
    PredictView,
    TrainView,
    SnapshotIngestJWTView,
    generation_view,
)
from rest_framework_simplejwt.views import (
    TokenObtainPairView, TokenRefreshView,
)
from django.views.defaults import bad_request, permission_denied, page_not_found, server_error

handler400 = bad_request
handler403 = permission_denied
handler404 = page_not_found
handler500 = server_error

router = routers.DefaultRouter()
router.register(r"recommendations", RecommendationViewSet, basename="recommendation")
router.register(r"feedbacks", FeedbackLoopViewSet, basename="feedback")
router.register(r"ai-models", AIModelVersionViewSet, basename="ai-model")
router.register(r"training-runs", TrainingRunViewSet, basename="training-run")
router.register(r"feature-snapshots", FeatureSnapshotViewSet, basename="feature-snapshot")

urlpatterns = router.urls + [
    path("predict", PredictView.as_view()),           
    path("train", TrainView.as_view()),       
    path("ingest/snapshot", SnapshotIngestJWTView.as_view()), 
    path("generate-recs/", generation_view.GenerateRecommendationView.as_view(), name="generate-recs"),
    path("token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
]

