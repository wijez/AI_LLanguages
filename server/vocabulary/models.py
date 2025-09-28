from django.db import models
from languages.models import Language


class Word(models.Model):
    language = models.ForeignKey(Language, on_delete=models.CASCADE, related_name='words')
    text = models.CharField(max_length=200)
    normalized = models.CharField(max_length=200, blank=True)
    part_of_speech = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('language', 'text')


class WordRelation(models.Model):
    word = models.ForeignKey(Word, on_delete=models.CASCADE, related_name='relations')
    related = models.ForeignKey(Word, on_delete=models.CASCADE, related_name='+')
    relation_type = models.CharField(max_length=50, blank=True)

    class Meta:
        unique_together = ('word', 'related', 'relation_type')


class KnownWord(models.Model):
    enrollment = models.ForeignKey("languages.LanguageEnrollment", on_delete=models.CASCADE, related_name='known_words')
    word = models.ForeignKey(Word, on_delete=models.CASCADE)
    score = models.FloatField(default=0.0)
    last_reviewed = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('enrollment', 'word')


class Translation(models.Model):
    source_language = models.ForeignKey(Language, on_delete=models.CASCADE, related_name='translations_out')
    target_language = models.ForeignKey(Language, on_delete=models.CASCADE, related_name='translations_in')
    source_text = models.TextField()
    translated_text = models.TextField()
    example = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AudioAsset(models.Model):
    language = models.ForeignKey(Language, on_delete=models.CASCADE, related_name='audio_assets')
    key = models.CharField(max_length=255)
    url = models.URLField()
    duration_ms = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('language', 'key')
