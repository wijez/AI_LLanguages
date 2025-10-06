from rest_framework import serializers
from .models import (
    UserLessonProgress, UserTopicProgress,
    UserSkillProgress, UserWordProgress
)


class UserLessonProgressSerializer(serializers.ModelSerializer):
    lesson_title = serializers.CharField(source="lesson.title", read_only=True)

    class Meta:
        model = UserLessonProgress
        fields = [
            "id", "lesson", "lesson_title", "completed", "score",
            "attempts", "last_activity"
        ]



class UserTopicProgressSerializer(serializers.ModelSerializer):
    topic_title = serializers.CharField(source="topic.title", read_only=True)

    class Meta:
        model = UserTopicProgress
        fields = [
            "id", "topic", "topic_title", "completed",
            "stars", "xp", "last_practiced"
        ]



class UserSkillProgressSerializer(serializers.ModelSerializer):
    skill_title = serializers.CharField(source="skill.title", read_only=True)

    class Meta:
        model = UserSkillProgress
        fields = [
            "id", "skill", "skill_title", "xp",
            "strength", "mastered", "last_practiced"
        ]


class UserWordProgressSerializer(serializers.ModelSerializer):
    word_text = serializers.CharField(source="word.text", read_only=True)

    class Meta:
        model = UserWordProgress
        fields = [
            "id", "word", "word_text", "times_seen",
            "times_correct", "times_wrong",
            "is_mastered", "last_seen"
        ]
