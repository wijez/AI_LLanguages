from django.db import models


class LearningInteraction(models.Model):
    user_id = models.IntegerField()
    enrollment_id = models.IntegerField()
    lesson_id = models.IntegerField(null=True, blank=True)
    action = models.CharField(max_length=50)  # "start_lesson", "complete_lesson", "review_word"
    success = models.BooleanField(default=True)
    duration_seconds = models.IntegerField(default=0)
    xp_earned = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
