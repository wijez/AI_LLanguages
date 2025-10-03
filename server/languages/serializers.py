from dataclasses import field
from rest_framework import serializers 
from vocabulary.models import (
    KnownWord
)
from languages.models import (
    Language, LanguageEnrollment, Lesson, Topic, TopicProgress, Skill,
     UserSkillStats
)


class LanguageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Language
        fields = '__all__'


class LanguageEnrollmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = LanguageEnrollment
        fields = '__all__'


class LessonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesson
        fields = '__all__'


class TopicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Topic
        fields = '__all__'


class TopicProgressSerializer(serializers.ModelSerializer):
    class Meta:
        model = TopicProgress
        fields = '__all__'


class SkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skill
        fields = '__all__'


class UserSkillStatsSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSkillStats
        fields = '__all__'


class UserSkillStatsExportSerializer(serializers.ModelSerializer):
    skill_id = serializers.IntegerField(source="skill.id")

    class Meta:
        model = UserSkillStats
        fields = ["skill_id", "xp", "proficiency_score"]


class KnownWordExportSerializer(serializers.ModelSerializer):
    word_id = serializers.IntegerField(source="word.id")

    class Meta:
        model = KnownWord
        fields = ["word_id", "score"]


class TopicProgressExportSerializer(serializers.ModelSerializer):
    topic_id = serializers.IntegerField(source="topic.id")

    class Meta:
        model = TopicProgress
        fields = ["topic_id", "completed", "xp", "reviewable"]


class LanguageEnrollmentExportSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id")
    language = serializers.CharField(source="language.abbreviation")
    skills = UserSkillStatsExportSerializer(source="skill_stats", many=True, read_only=True)
    known_words = KnownWordExportSerializer(source="known_words", many=True, read_only=True)
    topics = TopicProgressExportSerializer(source="topic_progress", many=True, read_only=True)

    class Meta:
        model = LanguageEnrollment
        fields = [
            "id", "user_id", "language",
            "total_xp", "streak_days",
            "skills", "known_words", "topics"
        ]
