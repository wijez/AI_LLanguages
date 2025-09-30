from rest_framework import routers
from .viewsets import (
    MistakeViewSet,
    AIModelVersionViewSet,
    RecommendationViewSet,
    LearningInteractionViewSet,
    FeedbackLoopViewSet,
)

router = routers.DefaultRouter()
router.register(r'mistakes', MistakeViewSet)
router.register(r'model-versions', AIModelVersionViewSet)
router.register(r'recommendations', RecommendationViewSet)
router.register(r'interactions', LearningInteractionViewSet)
router.register(r'feedbacks', FeedbackLoopViewSet)

urlpatterns = router.urls
