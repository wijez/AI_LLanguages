from django.db import models
from django.utils import timezone


class Mistake(models.Model):
    user_id = models.IntegerField()  # ID user từ BE
    enrollment_id = models.IntegerField()  # ID khóa học/ngôn ngữ
    prompt = models.TextField()  # câu gốc
    solution_translation = models.TextField(blank=True, null=True)
    mispronounced_words = models.JSONField(blank=True, null=True)  # list các từ sai
    timestamp = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Mistake of user {self.user_id} at {self.timestamp}"
