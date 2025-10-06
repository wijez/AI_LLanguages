import uuid
from django.db import models
from django.contrib.auth import get_user_model
from languages.models import Topic 


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, blank=True)
    topic = models.ForeignKey(Topic, on_delete=models.SET_NULL, null=True, blank=True)
    roleplay = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, default='active')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


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


class TopicScript(models.Model):
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name='scripts')
    step = models.PositiveIntegerField()
    prompt = models.TextField()
    hints = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ('topic', 'step')
        ordering = ['step']


class TopicKnowledge(models.Model):
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name='knowledge')
    title = models.TextField()
    content = models.TextField()