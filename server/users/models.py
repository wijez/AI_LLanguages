from django.db import models

from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from utils.gencode import generate_verify_code


class User(AbstractUser):
    avatar = models.URLField(blank=True, null=True)
    bio = models.TextField(blank=True)
    verify_code = models.CharField(
        max_length=6, 
        default=generate_verify_code, 
        blank=True, 
        null=True
    )
    last_active = models.DateTimeField(default=timezone.now)
    active_refresh_jti = models.CharField(
        max_length=255, 
        blank=True, 
        null=True, 
        unique=True
    )
    

class AccountSetting(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='settings')
    receive_notifications = models.BooleanField(default=True)
    ui_language = models.CharField(max_length=10, default='en')
    sound_on = models.BooleanField(default=True)
    difficulty_level = models.CharField(max_length=20, default='normal')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class AccountSwitch(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_switches')
    alias = models.CharField(max_length=150)
    linked_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='linked_as')
    active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['owner', 'alias'], name='uq_accountswitch_owner_alias')
        ]
