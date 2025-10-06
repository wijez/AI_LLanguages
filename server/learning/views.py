from rest_framework import viewsets, permissions
from .models import (
    UserLessonProgress, UserTopicProgress,
    UserSkillProgress, UserWordProgress
)
from .serializers import (
    UserLessonProgressSerializer, UserTopicProgressSerializer,
    UserSkillProgressSerializer, UserWordProgressSerializer
)

# Base class to auto filter by current user
class UserProgressViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # chỉ lấy tiến độ của user hiện tại
        return self.queryset.filter(enrollment__user=self.request.user)

    def perform_create(self, serializer):
        # tự động gắn enrollment của user nếu chưa có
        serializer.save()


class UserLessonProgressViewSet(UserProgressViewSet):
    queryset = UserLessonProgress.objects.all()
    serializer_class = UserLessonProgressSerializer


class UserTopicProgressViewSet(UserProgressViewSet):
    queryset = UserTopicProgress.objects.all()
    serializer_class = UserTopicProgressSerializer


class UserSkillProgressViewSet(UserProgressViewSet):
    queryset = UserSkillProgress.objects.all()
    serializer_class = UserSkillProgressSerializer


class UserWordProgressViewSet(UserProgressViewSet):
    queryset = UserWordProgress.objects.all()
    serializer_class = UserWordProgressSerializer
