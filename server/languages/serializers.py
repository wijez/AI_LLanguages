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
    skill = serializers.SerializerMethodField(read_only=True)
    skill_id = serializers.IntegerField(write_only=True, required=True)

    class Meta:
        model = Lesson
        fields = ["id", "title", "content", "xp_reward", "duration_seconds", "skill", "skill_id"]
        read_only_fields = ["id", "skill"]

    def get_skill(self, obj):
        s = getattr(obj, "skill", None)
        return None if not s else {
            "id": s.id,
            "title": getattr(s, "title", None) or getattr(s, "name", ""),
            "topic": getattr(getattr(s, "topic", None), "slug", None),
        }

    def create(self, validated_data):
        validated_data["skill_id"] = validated_data.pop("skill_id")
        return super().create(validated_data)

    def update(self, instance, validated_data):
        sid = validated_data.pop("skill_id", None)
        if sid is not None:
            instance.skill_id = sid
        return super().update(instance, validated_data)


class TopicSerializer(serializers.ModelSerializer):
    language = serializers.SlugRelatedField(
        slug_field="abbreviation",
        queryset=Language.objects.all()
    )

    class Meta:
        model = Topic
        fields = ["id", "slug", "title", "description", "order","golden", "language"]
        read_only_fields = ["id"]
    
 

class TopicProgressSerializer(serializers.ModelSerializer):
    class Meta:
        model = TopicProgress
        fields = '__all__'


class SkillSerializer(serializers.ModelSerializer):
    topic = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    class Meta:
        model = Skill
        fields = ["id","title","description","order","topic"]


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
