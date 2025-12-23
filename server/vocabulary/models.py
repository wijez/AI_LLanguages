from datetime import timedelta
from django.db import models
from languages.models import Language, LanguageEnrollment, Lesson, Skill
from users.models import User
from django.utils import timezone



class Word(models.Model):
    language = models.ForeignKey(Language, on_delete=models.CASCADE, related_name='words')
    text = models.CharField(max_length=200)
    normalized = models.CharField(max_length=200, blank=True)
    part_of_speech = models.CharField(max_length=50, blank=True)
    definition = models.TextField(blank=True, help_text="Nghĩa của từ")
    ipa = models.CharField(max_length=100, blank=True, help_text="Phiên âm, v.d: /həˈləʊ/")
    audio_url = models.URLField(max_length=500, blank=True, null=True, help_text="Link file phát âm")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['language', 'text'], name='uq_word_language_text')
        ]
        indexes = [models.Index(fields=['language', 'text'])]

    def __str__(self):
        return self.text
    
    def save(self, *args, **kwargs):
        if self.text:
            self.normalized = self.text.lower().strip()
        super().save(*args, **kwargs)


class KnownWord(models.Model):
    enrollment = models.ForeignKey("languages.LanguageEnrollment", on_delete=models.CASCADE, related_name='known_words')
    word = models.ForeignKey(Word, on_delete=models.CASCADE)
    score = models.FloatField(default=0.0)
    last_reviewed = models.DateTimeField(null=True, blank=True)
    ease_factor = models.FloatField(default=2.5, help_text="Ease factor (2.5 is default)")
    interval_days = models.IntegerField(default=1, help_text="Days until next review")
    repetitions = models.IntegerField(default=0, help_text="Number of successful repetitions")
    next_review = models.DateTimeField(null=True, blank=True, help_text="When to review next")
    STATUS_CHOICES = [
        ('new', 'New'),
        ('learning', 'Learning'),
        ('reviewing', 'Reviewing'),
        ('mastered', 'Mastered'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    
    # Statistics
    total_reviews = models.IntegerField(default=0)
    correct_reviews = models.IntegerField(default=0)
    times_forgotten = models.IntegerField(default=0)
    
    # Timestamps
    first_seen = models.DateTimeField(auto_now_add=True)
    mastered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['enrollment', 'word'], name='uq_knownword_enrollment_word_v2')
        ]
        indexes = [
            models.Index(fields=['enrollment', 'next_review']),
            models.Index(fields=['enrollment', 'status']),
            models.Index(fields=['next_review']),
        ]
    def __str__(self):
        return f"{self.word.text} - {self.status} (Score: {self.score})"
    
    def is_due_for_review(self):
        """Kiểm tra xem từ có cần ôn tập không"""
        if not self.next_review:
            return True
        return timezone.now() >= self.next_review
    
    def calculate_next_review(self, quality):
        """
        Tính toán lần review tiếp theo dựa trên quality of recall
        quality: 0-5 (0 = không nhớ, 5 = nhớ hoàn hảo)
        SM-2 Algorithm
        """
        self.total_reviews += 1
        
        # Update ease factor
        self.ease_factor = max(1.3, self.ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
        
        if quality < 3:
            # Forgot the word
            self.repetitions = 0
            self.interval_days = 1
            self.times_forgotten += 1
            self.status = 'learning'
        else:
            # Remembered correctly
            self.correct_reviews += 1
            self.repetitions += 1
            
            if self.repetitions == 1:
                self.interval_days = 1
                self.status = 'learning'
            elif self.repetitions == 2:
                self.interval_days = 6
                self.status = 'reviewing'
            else:
                self.interval_days = round(self.interval_days * self.ease_factor)
                self.status = 'reviewing'
            
            # Check if mastered (interval > 30 days and high accuracy)
            if self.interval_days > 30 and self.correct_reviews / max(1, self.total_reviews) > 0.9:
                self.status = 'mastered'
                if not self.mastered_at:
                    self.mastered_at = timezone.now()
        
        # Set next review date
        self.next_review = timezone.now() + timedelta(days=self.interval_days)
        self.last_reviewed = timezone.now()
        
        # Update score (0-100)
        self.score = min(100, (self.correct_reviews / max(1, self.total_reviews)) * 100)
        
        self.save()
    
    def review(self, correct):
        """
        Simple review interface
        correct: True/False
        """
        quality = 4 if correct else 2  # Map to 0-5 scale
        self.calculate_next_review(quality)
    
    def reset(self):
        """Reset progress"""
        self.ease_factor = 2.5
        self.interval_days = 1
        self.repetitions = 0
        self.status = 'new'
        self.next_review = timezone.now()
        self.save()


class Translation(models.Model):
    source_language = models.ForeignKey(Language, on_delete=models.CASCADE, related_name='translations_out')
    target_language = models.ForeignKey(Language, on_delete=models.CASCADE, related_name='translations_in')
    source_text = models.TextField()
    translated_text = models.TextField()
    example = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['source_language', 'target_language'])]


class LearningInteraction(models.Model):
    ACTIONS = [
        ("start_lesson", "Start Lesson"),
        ("complete_lesson", "Complete Lesson"),
        ("review_word", "Review Word"),
        ("practice_skill", "Practice Skill"),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='learning_interactions')
    enrollment = models.ForeignKey(LanguageEnrollment, on_delete=models.CASCADE, related_name='learning_interactions')
    lesson = models.ForeignKey(Lesson, on_delete=models.SET_NULL, null=True, blank=True)
    word = models.ForeignKey(Word, on_delete=models.SET_NULL, null=True, blank=True)
    skill = models.ForeignKey(Skill, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=50, choices=ACTIONS)
    value = models.FloatField(null=True, blank=True, help_text="điểm số/tỉ lệ đúng nếu có")
    success = models.BooleanField(default=True)
    duration_seconds = models.IntegerField(default=0)
    xp_earned = models.IntegerField(default=0)
    meta = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['enrollment', 'created_at']),
            models.Index(fields=['skill', 'created_at']),
            models.Index(fields=['lesson', 'created_at']),
            models.Index(fields=['action']),
            ]
        ordering = ['-created_at']


class Mistake(models.Model):
    SOURCE_CHOICES = [
        ("pronunciation", "Pronunciation"),
        ("grammar", "Grammar"),
        ("vocab", "Vocabulary"),
        ("listening", "Listening"),
        ("spelling", "Spelling"),
        ('other', 'Other'),
    ]
    skill = models.ForeignKey(Skill, on_delete=models.SET_NULL, null=True, blank=True, related_name="mistakes")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="mistakes")
    enrollment = models.ForeignKey(LanguageEnrollment, on_delete=models.CASCADE, related_name="mistakes")
    interaction = models.ForeignKey(LearningInteraction, on_delete=models.SET_NULL, null=True, blank=True, related_name="mistakes")
    lesson = models.ForeignKey(Lesson, on_delete=models.SET_NULL, null=True, blank=True)
    word = models.ForeignKey(Word, on_delete=models.SET_NULL, null=True, blank=True)

    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="grammar")
    prompt = models.TextField()
    expected = models.TextField(blank=True, null=True)
    user_answer = models.TextField(blank=True, null=True)

    mispronounced_words = models.JSONField(blank=True, null=True)
    error_detail = models.JSONField(blank=True, null=True)

    score = models.FloatField(blank=True, null=True)        # 0..1
    confidence = models.FloatField(blank=True, null=True)   # từ ASR/đánh giá
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['enrollment', 'timestamp']),
            models.Index(fields=['source']),
            models.Index(fields=['skill', 'timestamp'])
        ]