from django.utils import timezone
from django.db import models
from users.models import User

class Friend(models.Model):
    from_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='friends_sent')
    to_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='friends_received')
    accepted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['from_user', 'to_user'], name='uq_friend_from_to')
        ]
        indexes = [models.Index(fields=['from_user', 'to_user', 'accepted'])]


    def save(self, *args, **kwargs):
        # tự động cập nhật updated_at
        self.updated_at = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self):
        status = "Accepted" if self.accepted else "Pending"
        return f"{self.from_user.username} → {self.to_user.username} ({status})"


class CalendarEvent(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='calendar_events')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    start = models.DateTimeField()
    end = models.DateTimeField(null=True, blank=True)
    tz = models.CharField(max_length=50, default='UTC')
    created_at = models.DateTimeField(auto_now_add=True)


class LeaderboardEntry(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='leaderboard_entries')
    language = models.ForeignKey("languages.Language", on_delete=models.CASCADE, null=True, blank=True)
    date = models.DateField()
    rank = models.IntegerField()
    xp = models.IntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user','language','date'], name='uq_leaderboard_user_lang_date')
        ]
        indexes = [
            models.Index(fields=['language', 'date', '-xp'], name='idx_lb_lang_date_xp_desc'),
            models.Index(fields=['language', 'date', 'rank'], name='idx_lb_lang_date_rank'),
            models.Index(fields=['user', 'date'], name='idx_lb_user_date'),
        ]
        ordering = ['-date', 'rank']