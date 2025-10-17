from rest_framework import serializers
from vocabulary.models import KnownWord
from languages.models import (
    Language, LanguageEnrollment, Lesson, Topic, TopicProgress, Skill,
    UserSkillStats, LessonSkill
)
from django.db.models import Q
from django.utils.text import slugify


class LanguageListSerializer(serializers.ListSerializer):
    def create(self, validated_data):
        abbrs = [item["abbreviation"] for item in validated_data]

        seen = set()
        clean_items = []
        for it in validated_data:
            ab = it["abbreviation"]
            if ab not in seen:
                seen.add(ab)
                clean_items.append(it)

        objs = [Language(**item) for item in clean_items]
        Language.objects.bulk_create(objs, ignore_conflicts=True)

        return list(Language.objects.filter(abbreviation__in=abbrs))


class LanguageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Language
        fields = '__all__'
        list_serializer_class = LanguageListSerializer
    
    def validate_direction(self, v):
        v = (v or "").upper()
        if v not in ("LTR", "RTL"):
            raise serializers.ValidationError("direction must be 'LTR' or 'RTL'")
        return v


class LanguageEnrollmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = LanguageEnrollment
        fields = '__all__'


# ---- SỬA LẠI CHO B2: Lesson không còn FK skill; có FK topic + M2M skills ----
class SkillBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skill
        fields = ("id", "title", "type")

class LessonSerializer(serializers.ModelSerializer):
    topic = serializers.SerializerMethodField(read_only=True)
    topic_id = serializers.IntegerField(write_only=True, required=True)
    skills = SkillBriefSerializer(many=True, read_only=True)

    class Meta:
        model = Lesson
        fields = [
            "id", "title", "content", "xp_reward", "duration_seconds",
            "order", "topic", "topic_id", "skills"
        ]
        read_only_fields = ["id", "topic", "skills"]

    def get_topic(self, obj):
        t = obj.topic
        return {"id": t.id, "slug": t.slug, "title": t.title} if t else None


# (tuỳ chọn) Serializer cho bảng nối để gán skill vào lesson theo thứ tự
class LessonSkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = LessonSkill
        fields = ("lesson", "skill", "order")


class TopicListSerializer(serializers.ListSerializer):
    """
    Bulk create cho Topic:
    - Khử trùng lặp trong payload theo (language_id, slug)
    - bulk_create(ignore_conflicts=True) để idempotent
    - Refetch lại để trả về instance có id đầy đủ
    """
    def create(self, validated_data):
        clean = []
        seen = set()
        pairs = []  # (language_id, slug) để refetch

        for item in validated_data:
            lang = item["language"]  # instance Language (do SlugRelatedField resolve)
            if not item.get("slug"):
                item["slug"] = slugify(item["title"])
            item["slug"] = slugify(item["slug"])  # chuẩn hoá

            key = (lang.id, item["slug"])
            if key in seen:
                continue
            seen.add(key)
            pairs.append(key)
            clean.append(item)

        Topic.objects.bulk_create([Topic(**it) for it in clean], ignore_conflicts=True)

        # Refetch để có id cho cả cái mới vừa tạo lẫn cái đã tồn tại
        q = Q(pk__isnull=True)
        for lang_id, slug in pairs:
            q |= Q(language_id=lang_id, slug=slug)
        return list(Topic.objects.filter(q))


class TopicSerializer(serializers.ModelSerializer):
    language = serializers.SlugRelatedField(
        slug_field="abbreviation",
        queryset=Language.objects.all()
    )

    class Meta:
        model = Topic
        fields = ["id", "slug", "title", "description", "order", "golden", "language", "created_at"]
        read_only_fields = ["id", "created_at"]
        list_serializer_class = TopicListSerializer

    def validate_slug(self, v):
        return slugify(v) if v else v

    def create(self, validated_data):
        if not validated_data.get("slug"):
            validated_data["slug"] = slugify(validated_data["title"])
        else:
            validated_data["slug"] = slugify(validated_data["slug"])
        return super().create(validated_data)


class TopicProgressSerializer(serializers.ModelSerializer):
    topic_info = serializers.SerializerMethodField(read_only=True)
    language = serializers.CharField(source="enrollment.language.abbreviation", read_only=True)
    user_id = serializers.IntegerField(source="enrollment.user.id", read_only=True)

    class Meta:
        model = TopicProgress
        fields = ["id", "enrollment", "topic", "xp", "completed", "reviewable",
                  "topic_info", "language", "user_id"]
        read_only_fields = ["id", "topic_info", "language", "user_id"]

    def get_topic_info(self, obj):
        t = obj.topic
        return {"id": t.id, "slug": t.slug, "title": t.title}
        

# ---- SỬA LẠI CHO B2: Skill không còn topic/order; thêm các field bài tập ----
class SkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skill
        fields = [
            "id", "title", "slug", "description",
            "type", "content",
            "xp_reward", "duration_seconds",
            "difficulty", "language_code",
            "tags", "is_active",
        ]


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


# giữ nguyên nhưng bỏ select/order theo topic ở View (xem bên dưới)
class SkillStatsSerializer(serializers.ModelSerializer):
    skill_id = serializers.IntegerField(source="skill.id", read_only=True)
    skill_title = serializers.CharField(source="skill.title", read_only=True)

    class Meta:
        model = UserSkillStats
        fields = [
            "skill_id", "skill_title",
            "level", "proficiency_score",
            "last_practiced", "status", "needs_review",
            "lessons_completed_at_level", "lessons_required_for_next",
        ]


class AutoGenerateLessonsIn(serializers.Serializer):
    per_topic = serializers.IntegerField(min_value=1, required=False, default=5)
    langs = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True,
        help_text="Danh sách language abbreviation (vd: ['en','vi']). Bỏ trống = tất cả."
    )
    reset = serializers.BooleanField(required=False, default=False)

    def validate_langs(self, v):
        if v in (None, [], ()):
            return v
        # kiểm tra mã hợp lệ
        have = set(Language.objects.filter(abbreviation__in=v).values_list('abbreviation', flat=True))
        missing = [x for x in v if x not in have]
        if missing:
            raise serializers.ValidationError(f"Unknown language(s): {', '.join(missing)}")
        return v

class AutoGenerateLessonsOut(serializers.Serializer):
    created = serializers.IntegerField()
    topics = serializers.IntegerField()