# ai_recommend/viewsets/feedback_loop_viewset.py
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema
from ..models import FeedbackLoop, Recommendation
from ..serializers import FeedbackLoopSerializer

class FeedbackLoopViewSet(viewsets.ModelViewSet):
    serializer_class = FeedbackLoopSerializer
    permission_classes = [permissions.IsAuthenticated]
    ordering = ["-created_at"]

    def get_queryset(self):
        # Chỉ xem feedback gắn với recommendation của chính user
        user_id = getattr(self.request.user, "id", None)
        return FeedbackLoop.objects.filter(recommendation__user_id=user_id).order_by("-created_at")

    @extend_schema(summary="Tạo feedback cho recommendation thuộc về chính user")
    def create(self, request, *args, **kwargs):
        """
        Yêu cầu body có recommendation (id) hoặc bạn cho phép pass qua URL.
        Bảo đảm recommendation thuộc về user hiện tại.
        """
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        rec_id = ser.validated_data.get("recommendation").id if hasattr(ser.validated_data.get("recommendation"), "id") else ser.validated_data.get("recommendation")
        try:
            rec = Recommendation.objects.get(id=rec_id, user_id=request.user.id)
        except Recommendation.DoesNotExist:
            return Response({"detail": "Recommendation not found or not yours"}, status=status.HTTP_404_NOT_FOUND)
        ser.save(recommendation=rec)
        headers = self.get_success_headers(ser.data)
        return Response(ser.data, status=status.HTTP_201_CREATED, headers=headers)
