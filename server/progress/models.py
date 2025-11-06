from django.db import models
from users.models  import User
from django.utils import timezone


class DailyXP(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='daily_xp')
    date = models.DateField()
    xp = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'date'], name='uq_dailyxp_user_date')
        ]
        indexes = [models.Index(fields=['user', 'date'])]


class XPEvent(models.Model):
    """Log sự kiện thưởng XP để chống cộng trùng (idempotent).
    Ví dụ: source_type="lesson", source_id=session_id/lesson_id.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="xp_events")
    source_type = models.CharField(max_length=20) # "lesson", "bonus", ...
    source_id = models.CharField(max_length=64) # ví dụ session_id hoặc lesson_id
    amount = models.IntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
        models.UniqueConstraint(
        fields=["user", "source_type", "source_id"],
        name="uq_xpevent_user_source_unique",
        )
        ]
        indexes = [models.Index(fields=["user", "source_type", "source_id"])]


        def __str__(self):
            return f"XPEvent(user={self.user_id}, {self.source_type}:{self.source_id}, amount={self.amount})"