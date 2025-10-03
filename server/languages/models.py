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
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name='skills')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ['order']
        indexes = [models.Index(fields=['topic', 'order'])]


class Lesson(models.Model):
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name='lessons')
    title = models.CharField(max_length=255)
    content = models.JSONField(null=True, blank=True)
    xp_reward = models.IntegerField(default=10)
    duration_seconds = models.IntegerField(default=120)

    def __str__(self):
        return self.title


class UserSkillStats(models.Model):
    enrollment = models.ForeignKey(LanguageEnrollment, on_delete=models.CASCADE,  related_name='skill_stats')
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE)
    xp = models.IntegerField(default=0)
    last_practiced = models.DateTimeField(null=True, blank=True)
    proficiency_score = models.FloatField(default=0.0) 

    class Meta: 
        constraints = [
            models.UniqueConstraint(fields=['enrollment', 'skill'], name='uq_userskillstats_enrollment_skill')
        ]
        indexes = [models.Index(fields=['enrollment', 'skill'])]


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