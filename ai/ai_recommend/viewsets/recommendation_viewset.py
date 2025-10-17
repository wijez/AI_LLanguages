from django.db.models import Prefetch
from rest_framework import viewsets, permissions, filters, status
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema, OpenApiParameter
from ..models import Recommendation
from ..serializers import RecommendationSerializer

class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Chỉ owner được xem danh sách của mình; chặn update/delete nếu không phải owner.
    """
    def has_object_permission(self, request, view, obj):
        return getattr(obj, "user_id", None) == getattr(request.user, "id", None)

class RecommendationViewSet(viewsets.ModelViewSet):
    """
    GET /recommendations/             → list (lọc theo user)
    GET /recommendations/{id}/        → detail (chỉ owner)
    POST /recommendations/            → (tuỳ) chặn tạo thủ công nếu bạn chỉ muốn tạo từ pipeline
    PATCH/PUT/DELETE /recommendations/{id}/ → chỉ owner
    """
    serializer_class = RecommendationSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrReadOnly]
    filter_backends = [filters.OrderingFilter, filters.SearchFilter]
    # Tìm theo title (serializer sẽ resolve title), reasons/payload là JSON nên chỉ search cơ bản theo id
    search_fields = ["=id"]
    ordering_fields = ["priority_score", "created_at", "id"]
    ordering = ["-priority_score", "-created_at"]

    @extend_schema(
        parameters=[
            OpenApiParameter(name="limit", description="Giới hạn số bản ghi", required=False, type=int),
            OpenApiParameter(name="enrollment_id", description="Lọc theo enrollment_id", required=False, type=int),
            OpenApiParameter(name="accepted", description="true/false để lọc accepted", required=False, type=str),
        ]
    )
    def get_queryset(self):
        user = self.request.user
        qs = Recommendation.objects.filter(user_id=user.id)
        # Lọc thêm nếu cần
        enrollment_id = self.request.query_params.get("enrollment_id")
        if enrollment_id:
            qs = qs.filter(enrollment_id=enrollment_id)
        accepted = self.request.query_params.get("accepted")
        if accepted in ("true", "false"):
            qs = qs.filter(accepted=(accepted == "true"))
        # Prefetch/select_related nếu bạn có FK thực (ở đây các *_id là int thuần)
        return qs.order_by("-priority_score", "-created_at")

    def list(self, request, *args, **kwargs):
        limit = request.query_params.get("limit")
        if limit and str(limit).isdigit():
            self.pagination_class = None  # không phân trang nếu yêu cầu limit ngắn
            qs = self.get_queryset()[: int(limit)]
            ser = self.get_serializer(qs, many=True)
            return Response(ser.data)
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        """
        Nếu bạn KHÔNG muốn cho client tự tạo recommendation (chỉ pipeline tạo),
        hãy raise PermissionDenied. Nếu muốn cho tạo thủ công, ép user_id=owner.
        """
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied("Recommendations are materialized by the pipeline, not manually.")
        # Hoặc:
        # serializer.save(user_id=self.request.user.id)
