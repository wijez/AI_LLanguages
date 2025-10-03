# import requests
# from django.conf import settings
# from django.utils import timezone
# from rest_framework.decorators import api_view
# from rest_framework.response import Response
# from ..models import Recommendation
# from server.vocabulary.models import LearningInteraction, Mistake
# from server.vocabulary.serializers import LearningInteractionSerializer, MistakeSerializer


# BE_EXPORT_URL = "http://127.0.0.1:8000/api/export_learning_data/"


# @api_view(["POST"])
# def sync_learning_data(request):
#     """
#     Gọi API BE để sync dữ liệu học tập về AI DB
#     """
#     try:
#         resp = requests.get(BE_EXPORT_URL, timeout=30)
#         resp.raise_for_status()
#     except Exception as e:
#         return Response({"error": str(e)}, status=500)

#     data = resp.json().get("enrollments", [])
#     saved = 0

#     for e in data:
#         # log 1 interaction đại diện cho enrollment này
#         li = LearningInteraction.objects.create(
#             user_id=e["user_id"],
#             enrollment_id=e["id"],
#             action="sync_enrollment",
#             success=True,
#             duration_seconds=0,
#             xp_earned=e.get("total_xp", 0),
#         )

#         # Known words -> Mistakes
#         for w in e.get("known_words", []):
#             Mistake.objects.create(
#                 user_id=e["user_id"],
#                 enrollment_id=e["id"],
#                 prompt=f"Word {w['word_id']}",   # tạm thời log dạng text
#                 mispronounced_words=[w["word_id"]],
#                 timestamp=timezone.now()
#             )

#         # Skills -> Recommendations
#         for s in e.get("skills", []):
#             Recommendation.objects.create(
#                 user_id=e["user_id"],
#                 enrollment_id=e["id"],
#                 skill_id=s["skill_id"],
#                 priority_score=max(0, 1 - s.get("proficiency", 0)),
#             )

#         saved += 1

#     return Response({"synced": saved})