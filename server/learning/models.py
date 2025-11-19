from django.db import models
from django.utils import timezone
from users.models import User
from languages.models import LanguageEnrollment, Lesson, PronunciationPrompt, Skill

class LessonSession(models.Model):
    """
    Track một session làm bài lesson cụ thể
    Giống như khi user bắt đầu một lesson và làm từng câu hỏi
    """
    STATUS_CHOICES = [
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('abandoned', 'Abandoned'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='lesson_sessions')
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='sessions')
    enrollment = models.ForeignKey(LanguageEnrollment, on_delete=models.CASCADE, related_name='lesson_sessions')
    skill = models.ForeignKey(Skill, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Session info
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='in_progress')
    session_id = models.CharField(max_length=100, unique=True, blank=True)  # UUID cho session
    
    # Timestamps
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_activity = models.DateTimeField(auto_now=True)
    
    
    correct_answers = models.IntegerField(default=0)
    incorrect_answers = models.IntegerField(default=0)
    total_questions = models.IntegerField(default=0)
    
    # Rewards
    xp_earned = models.IntegerField(default=0)
    
    # Bonus tracking
    perfect_lesson = models.BooleanField(default=False, help_text="Không sai câu nào")
    speed_bonus = models.IntegerField(default=0)
    combo_bonus = models.IntegerField(default=0)
    
    # Additional data
    duration_seconds = models.IntegerField(default=0)
    answers_data = models.JSONField(default=dict, blank=True, help_text="Chi tiết từng câu trả lời")
    
    class Meta:
        indexes = [
            models.Index(fields=['user', 'started_at']),
            models.Index(fields=['enrollment', 'status']),
            models.Index(fields=['lesson', 'completed_at']),
            models.Index(fields=['status', 'last_activity']),
        ]
        ordering = ['-started_at']
    
    def __str__(self):
        return f"{self.user.username} - {self.lesson.title} ({self.status})"
    
    @property
    def accuracy(self):
        """Tính accuracy %"""
        if self.total_questions == 0:
            return 0
        return (self.correct_answers / self.total_questions) * 100
    
    @property
    def is_active(self):
        """Check session còn active không (trong 30 phút)"""
        if self.status != 'in_progress':
            return False
        return (timezone.now() - self.last_activity).total_seconds() < 1800
    
    def complete_session(self, final_xp=None):
        """Hoàn thành session và cập nhật rewards"""
        if self.status != 'in_progress':
            return False
        
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.duration_seconds = int((self.completed_at - self.started_at).total_seconds())
        
        # Check perfect lesson
        if self.incorrect_answers == 0 and self.total_questions > 0:
            self.perfect_lesson = True
            self.xp_earned += 10  # Bonus XP
        
        if final_xp:
            self.xp_earned = final_xp
        
        self.save()
        
        # Update enrollment XP
        self.enrollment.total_xp += self.xp_earned
        self.enrollment.save()
        
        return True
    
    def fail_session(self):
        """Fail session khi hết hearts"""
        self.status = 'failed'
        self.completed_at = timezone.now()
        self.save()
    
    def save(self, *args, **kwargs):
        # Auto generate session_id
        if not self.session_id:
            import uuid
            self.session_id = str(uuid.uuid4())
        super().save(*args, **kwargs)


class SessionAnswer(models.Model):
    session = models.ForeignKey(LessonSession, on_delete=models.CASCADE, related_name="answers")
    skill = models.ForeignKey(Skill, on_delete=models.SET_NULL, null=True, blank=True)
    question_id = models.CharField(max_length=64)
    is_correct = models.BooleanField(default=False)
    user_answer = models.TextField(blank=True)
    expected = models.TextField(blank=True)
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["session", "created_at"]),
            models.Index(fields=["skill", "created_at"]),
        ]


class SkillSession(models.Model):
    """
    Một phiên luyện tập theo từng Skill độc lập (ví dụ skill PRON/SPEAKING)
    Không bắt buộc Lesson, nhưng có thể gắn Lesson nếu skill đang thuộc lesson nào đó.
    """
    STATUS = [
        ('in_progress', 'In Progress'),
        ('completed',   'Completed'),
        ('failed',      'Failed'),
        ('abandoned',   'Abandoned'),
    ]
    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name='skill_sessions')
    enrollment  = models.ForeignKey(LanguageEnrollment, on_delete=models.CASCADE, related_name='skill_sessions')
    skill       = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name='sessions')
    lesson      = models.ForeignKey(Lesson, on_delete=models.SET_NULL, null=True, blank=True, related_name='skill_sessions')

    status      = models.CharField(max_length=20, choices=STATUS, default='in_progress')

    started_at     = models.DateTimeField(auto_now_add=True)
    completed_at   = models.DateTimeField(null=True, blank=True)
    last_activity  = models.DateTimeField(auto_now=True)

    attempts_count = models.IntegerField(default=0)
    best_score     = models.FloatField(default=0.0)
    avg_score      = models.FloatField(default=0.0)

    xp_earned         = models.IntegerField(default=0)
    duration_seconds  = models.IntegerField(default=0)
    meta              = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'started_at']),
            models.Index(fields=['enrollment', 'status']),
            models.Index(fields=['skill', 'last_activity']),
        ]
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.user.username} · SkillSession({self.skill_id}) · {self.status}"

    @property
    def is_active(self):
        if self.status != 'in_progress':
            return False
        return (timezone.now() - self.last_activity).total_seconds() < 1800

    def _recalc_scores(self):
        atts = list(self.attempts.all().values_list('score_overall', flat=True))
        if not atts:
            self.best_score = 0.0
            self.avg_score  = 0.0
            self.attempts_count = 0
            return
        self.attempts_count = len(atts)
        self.best_score = float(max(atts))
        self.avg_score  = float(sum(atts) / max(1, len(atts)))

    def mark_completed(self, final_xp=None):
        if self.status != 'in_progress':
            return
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.duration_seconds = int((self.completed_at - self.started_at).total_seconds())
        if final_xp is not None:
            self.xp_earned = int(final_xp)
        self.save(update_fields=['status', 'completed_at', 'duration_seconds', 'xp_earned'])


class PronAttempt(models.Model):
    """
    Lưu từng lần ghi âm + chấm điểm PRON từ /speech/pron/up/ gắn vào SkillSession.
    """
    session      = models.ForeignKey(SkillSession, on_delete=models.CASCADE, related_name='attempts')
    prompt_id    = models.ForeignKey(PronunciationPrompt, on_delete=models.SET_NULL, null=True, blank=True)
    expected_text = models.TextField(blank=True, default="")
    recognized    = models.TextField(blank=True, default="")
    score_overall = models.FloatField(default=0.0)

    words   = models.JSONField(default=list, blank=True)   # list các word {word, score, start, end, status}
    details = models.JSONField(default=dict, blank=True)   # wer/cer/conf/duration/speed_sps/low_confidence…
    audio_path = models.CharField(max_length=255, blank=True, default="")  # MEDIA relative path (vd: tmp_upload/xxxx.mp3)

    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['session', 'created_at']),
            models.Index(fields=['score_overall']),
        ]

    def __str__(self):
        return f"PronAttempt({self.session_id if hasattr(self,'session_id') else self.session_id}) score={self.score_overall}"