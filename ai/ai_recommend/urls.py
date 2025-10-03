from rest_framework import routers
from .viewsets import (
    AIModelVersionViewSet,
    RecommendationViewSet,
    FeedbackLoopViewSet,
)

router = routers.DefaultRouter()
router.register(r'model-versions', AIModelVersionViewSet)
router.register(r'recommendations', RecommendationViewSet)
router.register(r'feedbacks', FeedbackLoopViewSet)

urlpatterns = router.urls
