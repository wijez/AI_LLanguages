from django.utils import timezone
from django.db import models
from users.models import User
from django.conf import settings
from utils._enum import STATUS, KIND

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
    
    kind = models.CharField(max_length=20, choices=KIND, default="personal")
    meta = models.JSONField(default=dict, blank=True)  # ví dụ: {"boost_multiplier":2, "target_xp":50}
    remind_before_min = models.IntegerField(default=0)  # 0 = không nhắc
    rrule = models.CharField(max_length=255, blank=True)  # RRULE lặp lại (iCal chuỗi)
    is_all_day = models.BooleanField(default=False)

    # Người tham gia (cho duel/study_group/quest)
    participants = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="event_participants", blank=True)
   
    status = models.CharField(max_length=20, choices=STATUS, default="scheduled")  

    class Meta:
        indexes = [
            models.Index(fields=["user", "start"]),
            models.Index(fields=["kind", "start"]),
        ]


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


class Badge(models.Model):
    slug = models.SlugField(max_length=100, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=255, blank=True)  # URL hoặc key icon
    is_active = models.BooleanField(default=True)
    criteria = models.JSONField(default=dict, blank=True)  # ví dụ: {"type":"streak","days":7}
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class UserBadge(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="badges")
    badge = models.ForeignKey(Badge, on_delete=models.CASCADE)
    awarded_at = models.DateTimeField(auto_now_add=True)
    progress = models.IntegerField(default=0)  # nếu badge dạng tiến độ
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user","badge"], name="uq_userbadge_user_badge")
        ]
        indexes = [models.Index(fields=["user","awarded_at"])]


class Notification(models.Model):
    TYPE = [
        ("event_reminder", "Event Reminder"),
        ("quest_update", "Quest Update"),
        ("league_reset", "League Reset"),
        ("streak_alert", "Streak Alert"),
        ("system", "System"),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    type = models.CharField(max_length=30, choices=TYPE, default="system")
    title = models.CharField(max_length=200, blank=True)
    body = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)  # deep link, ids...
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["user", "read_at"]),
        ]
        ordering = ["-created_at"]
