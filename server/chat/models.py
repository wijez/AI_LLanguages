from datetime import timezone
import uuid
from django.db import models
from django.contrib.auth import get_user_model
from languages.models import Topic 



class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    topic = models.ForeignKey(Topic, on_delete=models.PROTECT, related_name='conversations')
    # roleplay config tối giản
    use_rag = models.BooleanField(default=True)
    temperature = models.FloatField(default=0.4)
    max_tokens = models.IntegerField(default=300)
    suggestions_count = models.IntegerField(default=2)
    knowledge_limit = models.IntegerField(default=3)
    created_at = models.DateTimeField(auto_now_add=True)


class Turn(models.Model):
    ROLE_CHOICES = (
    ('system', 'system'),
    ('user', 'user'),
    ('assistant', 'assistant'),
    )
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='turns')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


    class Meta:
        ordering = ['id']
