from django.utils import timezone
from django.db import models
from users.models import User

class Language(models.Model):
    name = models.CharField(max_length=100)
    abbreviation = models.CharField(max_length=10, unique=True)
    native_name = models.CharField(max_length=100, blank=True)
    direction = models.CharField(max_length=3, default='LTR')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.abbreviation})"


class LanguageEnrollment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='enrollments')
    language = models.ForeignKey(Language, on_delete=models.CASCADE, related_name='enrollments')
    level = models.IntegerField(default=0)
    total_xp = models.IntegerField(default=0)
    streak_days = models.IntegerField(default=0)
    last_practiced = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'language'], name='uq_enrollment_user_language')
        ]
        indexes = [models.Index(fields=['user', 'language'])]


class Topic(models.Model):
    language = models.ForeignKey(Language, on_delete=models.CASCADE, related_name='topics')
    slug = models.SlugField(max_length=150)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    order = models.IntegerField(default=0)
    golden = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['language', 'slug'], name='uq_topic_language_slug')
        ]
        ordering = ['order']
        indexes = [models.Index(fields=['language', 'order'])]

    def __str__(self):
        return f'{self.title}({self.language})'


class TopicProgress(models.Model):
    enrollment = models.ForeignKey(LanguageEnrollment, on_delete=models.CASCADE, related_name='topic_progress')
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE)
    completed = models.BooleanField(default=False)
    xp = models.IntegerField(default=0)
    last_seen = models.DateTimeField(null=True, blank=True)
    reviewable = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['enrollment', 'topic'], name='uq_topicprogress_enrollment_topic')
        ]
        indexes = [models.Index(fields=['enrollment', 'completed', 'reviewable'])]


class Skill(models.Model):
    class SkillType(models.TextChoices):
        LISTENING = "listening", "Listening"
        SPEAKING  = "speaking",  "Speaking"
        READING   = "reading",   "Reading"
        WRITING   = "writing",   "Writing"
        MATCHING  = "matching",  "Matching"   # ghép từ / nối cặp
        FILLGAP   = "fillgap",   "Fill in the blanks"
        ORDERING  = "ordering",  "Reorder words"
        QUIZ      = "quiz",      "Generic MCQ/QA"
        PRON      = "pron",      "Pronunciation"

    # Skill dùng chung nhiều lesson (B2)
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=150, blank=True)
    description = models.TextField(blank=True)

    # Thuộc tính quan trọng cho “bài tập”
    type = models.CharField(max_length=32, choices=SkillType.choices,  default=SkillType.QUIZ)
    content = models.JSONField(null=True, blank=True)  # chứa cấu trúc exercises
    xp_reward = models.IntegerField(default=10)
    duration_seconds = models.IntegerField(default=90)
    difficulty = models.PositiveSmallIntegerField(default=1)  # 1..5
    language_code = models.CharField(max_length=10, default="en")  # en/vi/…

    # Metadata
    tags = models.JSONField(default=list, blank=True)  # ["A1","greetings"]
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["type"]), models.Index(fields=["language_code"])]

    def __str__(self):
        return f"{self.title} [{self.type}]"


class Lesson(models.Model):
    topic = models.ForeignKey("Topic", on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField(max_length=255)
    content = models.JSONField(null=True, blank=True)  # optional: mô tả chung
    order = models.IntegerField(default=0)
    xp_reward = models.IntegerField(default=10)
    duration_seconds = models.IntegerField(default=120)

    # Liên kết N–N tới skill (có thứ tự hiển thị trong 1 lesson)
    skills = models.ManyToManyField(Skill, related_name="lessons", through="LessonSkill")

    class Meta:
        ordering = ["order", "id"]
        indexes = [models.Index(fields=["topic", "order"])]

    def __str__(self):
        return self.title


class LessonSkill(models.Model):
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE)
    skill  = models.ForeignKey(Skill, on_delete=models.CASCADE)
    order  = models.IntegerField(default=0)

    class Meta:
        unique_together = ("lesson", "skill")
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["lesson", "order"]),
            models.Index(fields=["skill", "order"]),
        ]

    def __str__(self):
        return f"{self.lesson} ↔ {self.skill} (#{self.order})"



class UserSkillStats(models.Model):
    enrollment = models.ForeignKey(LanguageEnrollment, on_delete=models.CASCADE,  related_name='skill_stats')
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE)
    xp = models.IntegerField(default=0)
    total_lessons_completed = models.IntegerField(default=0)
    last_practiced = models.DateTimeField(null=True, blank=True)
    proficiency_score = models.FloatField(default=0.0) 
    level = models.IntegerField(default=0, help_text="Crown level 0-5")
    lessons_completed_at_level = models.IntegerField(default=0, help_text="Lessons completed at current level")
    lessons_required_for_next = models.IntegerField(default=5, help_text="Lessons needed to level up")
    # Review tracking
    needs_review = models.BooleanField(default=False)
    review_reminder_date = models.DateField(null=True, blank=True)
    STATUS_CHOICES = [
        ('locked', 'Locked'),
        ('available', 'Available'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('mastered', 'Mastered'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='locked')
    
    # Timestamps
    unlocked_at = models.DateTimeField(null=True, blank=True)
    first_completed_at = models.DateTimeField(null=True, blank=True)
    mastered_at = models.DateTimeField(null=True, blank=True)

    class Meta: 
        constraints = [
            models.UniqueConstraint(fields=['enrollment', 'skill'], name='uq_userskillstats_enrollment_skill_v2')
        ]
        indexes = [
            models.Index(fields=['enrollment', 'skill']),
            models.Index(fields=['enrollment', 'level']),
            models.Index(fields=['needs_review', 'review_reminder_date']),
        ]
    
    def __str__(self):
        return f"{self.skill.title} - Level {self.level} ({self.status})"
    
    @property
    def is_maxed(self):
        """Đã đạt level 5 chưa"""
        return self.level >= 5
    
    @property
    def progress_to_next_level(self):
        """% progress to next crown"""
        if self.is_maxed:
            return 100
        return (self.lessons_completed_at_level / self.lessons_required_for_next) * 100
    
    def complete_lesson(self, xp_earned=10):
        """Cập nhật khi hoàn thành một lesson"""
        self.total_lessons_completed += 1
        self.lessons_completed_at_level += 1
        self.xp += xp_earned
        self.last_practiced = timezone.now()
        
        if self.status == 'available':
            self.status = 'in_progress'
        
        # Check for level up
        if not self.is_maxed and self.lessons_completed_at_level >= self.lessons_required_for_next:
            self.level_up()
        
        # Update proficiency
        self._update_proficiency()
        
        self.save()
    
    def level_up(self):
        """Tăng crown level"""
        if self.is_maxed:
            return False
        
        self.level += 1
        self.lessons_completed_at_level = 0
        
        # Increase difficulty for next level
        self.lessons_required_for_next = 5 + (self.level * 2)  # 5, 7, 9, 11, 13
        
        if self.level == 5:
            self.status = 'mastered'
            self.mastered_at = timezone.now()
        elif not self.first_completed_at:
            self.status = 'completed'
            self.first_completed_at = timezone.now()
        
        self.save()
        return True
    
    def _update_proficiency(self):
        """Cập nhật proficiency score dựa trên level và accuracy"""
        base_score = self.level * 20  # Each level = 20 points
        # Add bonus based on completion
        completion_bonus = min(20, (self.lessons_completed_at_level / self.lessons_required_for_next) * 20)
        self.proficiency_score = min(100, base_score + completion_bonus)
    
    def mark_for_review(self):
        """Đánh dấu skill cần ôn tập"""
        self.needs_review = True
        self.review_reminder_date = timezone.now().date()
        self.save()
    
    def unlock(self):
        """Mở khóa skill"""
        if self.status == 'locked':
            self.status = 'available'
            self.unlocked_at = timezone.now()
            self.save()


# class SuggestedLesson(models.Model):
#     user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='suggested_lessons')
#     lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE)
#     priority_score = models.FloatField(default=0.0)
#     recommended_at = models.DateTimeField(auto_now_add=True)

#     class Meta:
#         constraints = [
#             models.UniqueConstraint(fields=['enrollment', 'skill'], name='uq_userskillstats_enrollment_skill')
#         ]
#         indexes = [models.Index(fields=['enrollment', 'skill'])]