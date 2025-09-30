from django.db import models
from ..models import Recommendation

class FeedbackLoop(models.Model):
    recommendation = models.ForeignKey(Recommendation, on_delete=models.CASCADE, related_name='feedbacks')
    outcome = models.CharField(max_length=50)  # "completed", "skipped", "failed"
    time_spent = models.IntegerField(default=0)  # giây
    xp_gain = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)