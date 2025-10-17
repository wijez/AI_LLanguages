from django.db import models
from ..models import AIModelVersion

class Recommendation(models.Model):
    user_id = models.IntegerField()
    enrollment_id = models.IntegerField()
    lesson_id = models.IntegerField(null=True, blank=True)
    skill_id = models.IntegerField(null=True, blank=True)
    word_id = models.IntegerField(null=True, blank=True)
    rec_type = models.CharField(max_length=20, default='practice')  # review | practice | challenge | word
    reasons = models.JSONField(default=list, blank=True)            # ["Đã 3 ngày chưa luyện", "3 lỗi gần đây", ...]
    batch_id = models.CharField(max_length=64, blank=True, db_index=True)
    language = models.CharField(max_length=10, blank=True, default='')
    priority_score = models.FloatField(default=0.0)
    model_used = models.ForeignKey(AIModelVersion, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    accepted = models.BooleanField(default=False)  # user có học theo gợi ý không?

    class Meta:
        indexes = [
            models.Index(fields=['user_id', 'created_at']),
            models.Index(fields=['user_id', 'priority_score']),
            models.Index(fields=['batch_id']),
            ]