from django.db import models
from users.models  import User


class DailyXP(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='daily_xp')
    date = models.DateField()
    xp = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'date'], name='uq_dailyxp_user_date')
        ]
        indexes = [models.Index(fields=['user', 'date'])]
