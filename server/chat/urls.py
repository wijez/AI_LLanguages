from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import TopicViewSet, ChatViewSet, RAGSearchView




router = DefaultRouter()
router.register(r'topics', TopicViewSet, basename='topic')
router.register(r'chat', ChatViewSet, basename='chat')


urlpatterns = router.urls + [
    path("api/rag/search", RAGSearchView.as_view(), name="rag-search"),
]