from rest_framework import serializers

from languages.serializers import PracticeSessionSerializer
from vocabulary.models import KnownWord, Word
from .models import (
    LessonSession, PronAttempt, SessionAnswer, SkillSession
)
from languages.models import (
    Lesson, LanguageEnrollment, PracticeSession, RoleplayScenario, Skill
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


class EnrollmentMiniSerializer(serializers.ModelSerializer):
    language_code = serializers.SerializerMethodField()
    class Meta:
        model = LanguageEnrollment
        fields = ("id", "language_code", "total_xp", "last_practiced")
        read_only_fields = fields
    def get_language_code(self, obj):
        lang = getattr(obj, "language", None)
        return (
            getattr(lang, "abbreviation", None)
            or getattr(lang, "abbr", None)
            or getattr(lang, "code", None)
            or getattr(lang, "lang", None)
        )

class WordMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Word
        fields = ("id", "text", "part_of_speech", "ipa")
        read_only_fields = fields

class KnownWordDueSerializer(serializers.ModelSerializer):
    word = WordMiniSerializer()
    # API vẫn trả 'due_at' nhưng map từ 'next_review'
    due_at = serializers.DateTimeField(source="next_review", allow_null=True)
    strength = serializers.SerializerMethodField()
    class Meta:
        model = KnownWord
        fields = ("id", "word", "due_at", "strength")
        read_only_fields = fields
    def get_strength(self, obj):
        return (
            getattr(obj, "score", None)
            or getattr(obj, "ease_factor", None)
            or getattr(obj, "repetitions", None)
        )

class MistakeAggSerializer(serializers.Serializer):
    word_id = serializers.IntegerField(required=False, allow_null=True)
    word_text = serializers.CharField(allow_blank=True, required=False)
    error_type = serializers.CharField()
    times = serializers.IntegerField()
    last_seen = serializers.DateTimeField(allow_null=True)

class WeakSkillSerializer(serializers.Serializer):
    skill_tag = serializers.CharField()
    accuracy = serializers.FloatField()

class LessonMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesson
        fields = ("id", "title", "order")
        read_only_fields = fields

class MicroLessonSerializer(serializers.ModelSerializer):
    lesson = LessonMiniSerializer()
    class Meta:
        model = LessonSession
        fields = ("id", "status", "started_at", "completed_at", "lesson")
        read_only_fields = fields

class RoleplayMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoleplayScenario
        fields = ("id", "title", "level")
        read_only_fields = fields


class WordSuggestSerializer(serializers.ModelSerializer):
    # tuỳ schema Word, nếu có trường cefr/level thì map ra:
    level = serializers.CharField(source="cefr", required=False, allow_null=True)

    class Meta:
        model = Word
        fields = ("id", "text", "part_of_speech", "level")
        read_only_fields = fields


class PracticeOverviewSerializer(serializers.Serializer):
    enrollment = EnrollmentMiniSerializer()
    xp_today = serializers.IntegerField()
    daily_goal = serializers.IntegerField()
    srs_due_words = KnownWordDueSerializer(many=True)
    common_mistakes = MistakeAggSerializer(many=True)
    weak_skills = WeakSkillSerializer(many=True)
    micro_lessons = MicroLessonSerializer(many=True)
    speak_listen = PracticeSessionSerializer(many=True)
    word_suggestions = WordSuggestSerializer(many=True)


class SkillSessionStartIn(serializers.Serializer):
    skill = serializers.PrimaryKeyRelatedField(queryset=Skill.objects.all())
    enrollment = serializers.PrimaryKeyRelatedField(queryset=LanguageEnrollment.objects.all())
    lesson = serializers.PrimaryKeyRelatedField(queryset=Lesson.objects.all(), required=False, allow_null=True)

class SkillSessionOut(serializers.ModelSerializer):
    skill_title = serializers.CharField(source='skill.title', read_only=True)
    skill_type = serializers.CharField(source='skill.type', read_only=True)
    lesson_title = serializers.CharField(source='lesson.title', read_only=True)
    class Meta:
        model = SkillSession
        fields = [
            "id", "skill", "lesson", "enrollment", "status",
            "skill_title", "skill_type",
            "lesson_title",
            "started_at", "completed_at", "last_activity",
            "attempts_count", "best_score", "avg_score",
            "xp_earned", "duration_seconds", "meta",
        ]

class PronAttemptOut(serializers.ModelSerializer):
    class Meta:
        model = PronAttempt
        fields = [
            "id", "created_at", "expected_text", "recognized", "score_overall",
            "words", "details", "audio_path", "prompt_id",
        ]



