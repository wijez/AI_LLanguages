from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from drf_spectacular.utils import extend_schema, OpenApiParameter
from ..services.generate_recommendations import generate_recommendations_for_user

class GenerateRecommendationView(APIView):
    """
    API endpoint để kích hoạt tạo gợi ý cá nhân cho 1 user.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'enrollment_id': {'type': 'integer', 'description': 'ID của enrollment (bắt buộc)'},
                    'language': {'type': 'string', 'description': 'Ngôn ngữ (ví dụ: "en") (bắt buộc)'},
                    'top_k_skills': {'type': 'integer', 'description': 'Số skill gợi ý (mặc định: 5)'},
                    'top_n_words': {'type': 'integer', 'description': 'Số từ vựng gợi ý (mặc định: 10)'},
                }
            }
        },
        summary="Kích hoạt tạo gợi ý cá nhân cho user hiện tại"
    )
    def post(self, request, *args, **kwargs):
        user_id = request.user.id
        if not user_id:
            return Response({"detail": "Xác thực thất bại."}, status=status.HTTP_401_UNAUTHORIZED)

        enrollment_id = request.data.get("enrollment_id")
        language = request.data.get("language")
        
        if enrollment_id is None or not language:
            return Response({"detail": "Yêu cầu 'enrollment_id' và 'language'"}, status=status.HTTP_400_BAD_REQUEST)

        top_k = request.data.get("top_k_skills", 5)
        top_n = request.data.get("top_n_words", 10)

        try:
            rec_ids = generate_recommendations_for_user(
                user_id=user_id,
                enrollment_id=enrollment_id,
                language=language,
                top_k=top_k,
                top_n_words=top_n
            )
            
            return Response(
                {"detail": f"Đã tạo thành công {len(rec_ids)} gợi ý.", "recommendation_ids": rec_ids},
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            return Response({"detail": f"Lỗi khi tạo gợi ý: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)