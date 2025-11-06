from rest_framework import serializers
from .models import (
    LessonSession, SessionAnswer
)
from languages.models import (
    Lesson, LanguageEnrollment, Skill
)


class LessonSessionOut(serializers.ModelSerializer):
    class Meta:
        model = LessonSession
        fields = [
            "id", "session_id", "lesson", "enrollment", "status",
            "started_at", "completed_at", "last_activity",
            "correct_answers", "incorrect_answers", "total_questions",
            "xp_earned", "perfect_lesson", "speed_bonus", "combo_bonus",
            "duration_seconds"
        ]

class StartSessionIn(serializers.Serializer):
    lesson = serializers.PrimaryKeyRelatedField(queryset=Lesson.objects.all())
    enrollment = serializers.PrimaryKeyRelatedField(queryset=LanguageEnrollment.objects.all())

class AnswerIn(serializers.Serializer):
    # gọi vào /sessions/{id}/answer/
    skill = serializers.PrimaryKeyRelatedField(queryset=Skill.objects.all())
    question_id = serializers.CharField()
    # is_correct = serializers.BooleanField()
    user_answer = serializers.CharField(allow_blank=True, required=False)
    expected = serializers.CharField(allow_blank=True, required=False)
    score = serializers.FloatField(required=False, allow_null=True)
    source = serializers.ChoiceField(
        choices=["pronunciation","grammar","vocab","listening","spelling","other"],
        required=False
    )
    duration_seconds = serializers.IntegerField(required=False)
    xp_on_correct = serializers.IntegerField(required=False, min_value=0, default=5)
    choice_id = serializers.IntegerField(required=False, allow_null=True)
    
class CompleteSessionIn(serializers.Serializer):
    # cho phép client ép tổng XP nếu muốn, nếu không sẽ dùng xp_earned trong session
    final_xp = serializers.IntegerField(required=False, min_value=0)

class CancelSessionIn(serializers.Serializer):
    as_failed = serializers.BooleanField(required=False, default=False)
    reason = serializers.CharField(required=False, allow_blank=True)

