import uuid
from django.db import models
from django.utils import timezone
from chat.models import Conversation

class TargetUtterance(models.Model):
    text = models.CharField(max_length=300)
    ipa = models.CharField(max_length=300, blank=True, default='')
    language_code = models.CharField(max_length=16, default='en')

    def __str__(self):
        return self.text

class PronunciationAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(Conversation, on_delete=models.SET_NULL, null=True, blank=True)
    target = models.ForeignKey(TargetUtterance, on_delete=models.SET_NULL, null=True, blank=True)
    target_text = models.CharField(max_length=300, blank=True, default='')
    language_code = models.CharField(max_length=16, default='en')
    audio = models.FileField(upload_to='pron_attempts/')
    scores = models.JSONField(default=dict, blank=True)
    words = models.JSONField(default=list, blank=True)
    suggestions = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
