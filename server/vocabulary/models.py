from django.db import models
from languages.models import Language, LanguageEnrollment, Lesson, Skill
from users.models import User
from django.utils import timezone


class Word(models.Model):
    language = models.ForeignKey(Language, on_delete=models.CASCADE, related_name='words')
    text = models.CharField(max_length=200)
    normalized = models.CharField(max_length=200, blank=True)
    part_of_speech = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['language', 'text'], name='uq_word_language_text')
        ]
        indexes = [models.Index(fields=['language', 'text'])]

    def __str__(self):
        return self.text


class WordRelation(models.Model):
    word = models.ForeignKey(Word, on_delete=models.CASCADE, related_name='relations')
    related = models.ForeignKey(Word, on_delete=models.CASCADE, related_name='+')
    relation_type = models.CharField(max_length=50, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['word', 'related', 'relation_type'],
                                    name='uq_wordrelation_word_related_type')
        ]
        indexes = [models.Index(fields=['relation_type'])]


class KnownWord(models.Model):
    enrollment = models.ForeignKey("languages.LanguageEnrollment", on_delete=models.CASCADE, related_name='known_words')
    word = models.ForeignKey(Word, on_delete=models.CASCADE)
    score = models.FloatField(default=0.0)
    last_reviewed = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['enrollment', 'word'], name='uq_knownword_enrollment_word')
        ]
        indexes = [models.Index(fields=['enrollment', 'score'])]


class Translation(models.Model):
    source_language = models.ForeignKey(Language, on_delete=models.CASCADE, related_name='translations_out')
    target_language = models.ForeignKey(Language, on_delete=models.CASCADE, related_name='translations_in')
    source_text = models.TextField()
    translated_text = models.TextField()
    example = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['source_language', 'target_language'])]


class AudioAsset(models.Model):
    language = models.ForeignKey(Language, on_delete=models.CASCADE, related_name='audio_assets')
    key = models.CharField(max_length=255)
    url = models.URLField()
    duration_ms = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['language', 'key'], name='uq_audioasset_language_key')
        ]


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
    skill = models.ForeignKey(Skill, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=50, choices=ACTIONS)
    success = models.BooleanField(default=True)
    duration_seconds = models.IntegerField(default=0)
    xp_earned = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['user', 'created_at'])]


class Mistake(models.Model):
    SOURCE_CHOICES = [
        ("pronunciation", "Pronunciation"),
        ("grammar", "Grammar"),
        ("vocab", "Vocabulary"),
        ("listening", "Listening"),
        ("spelling", "Spelling"),
    ]
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
            models.Index(fields=['source'])
        ]