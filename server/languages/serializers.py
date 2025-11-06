from rest_framework import serializers
from vocabulary.models import KnownWord
from languages.models import *
from django.db.models import Q
from django.utils.text import slugify
from django.db import transaction, IntegrityError
from rest_framework import serializers


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
    code = serializers.CharField(source="abbreviation", read_only=True)

    class Meta:
        model = Language
        fields = "__all__" 

    def validate_direction(self, v):
        v = (v or "").upper()
        if v not in ("LTR", "RTL"):
            raise serializers.ValidationError("direction must be 'LTR' or 'RTL'")
        return v


class LanguageEnrollmentSerializer(serializers.ModelSerializer):
    abbreviation  = serializers.CharField(write_only=True, required=False, allow_blank=True)
    language_code = serializers.CharField(write_only=True, required=False)
    language_id = serializers.IntegerField(write_only=True, required=False)

    language = LanguageSerializer(read_only=True)

    class Meta:
        model = LanguageEnrollment
        fields = "__all__"
        read_only_fields = ["total_xp", "streak_days", "last_practiced", "created_at", "user"]
        extra_kwargs = {
            "user": {"read_only": True},  
        }

    def validate(self, attrs):
        abbr = attrs.pop("abbreviation", None) or attrs.pop("language_code", None)
        lng_id = attrs.pop("language_id", None)

        if not abbr and not lng_id:
            raise serializers.ValidationError("Provide either language_code or language_id.")
        if abbr and lng_id:
            raise serializers.ValidationError("Provide only one of language_code or language_id.")

        if abbr:
            lang = Language.objects.filter(abbreviation__iexact=abbr).first()
        else:
            lang = Language.objects.filter(id=lng_id).first()

        if not lang:
            raise serializers.ValidationError("Language not found.")

        attrs["language"] = lang
        return attrs

    def create(self, validated_data):
        """
        Idempotent create: nếu (user, language) đã tồn tại → trả bản ghi cũ.
        """
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            raise serializers.ValidationError("Authentication required.")

        language = validated_data["language"]
        level = validated_data.get("level", 0)

        try:
            with transaction.atomic():
                obj, created = LanguageEnrollment.objects.get_or_create(
                    user=user,
                    language=language,
                    defaults={"level": level},
                )
        except IntegrityError:
            obj = LanguageEnrollment.objects.get(user=user, language=language)
            created = False

        self.context["__created__"] = created
        return obj


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
    unlock_order = serializers.SerializerMethodField(read_only=True)
    class Meta:
        model = TopicProgress
        fields = ["id", "enrollment", "topic",'highest_completed_order', "xp", "completed", "reviewable",
                  "topic_info", "language",   "unlock_order",   "user_id"]
        read_only_fields = ["id", "topic_info", "language", "user_id",  "unlock_order" ]

    def get_topic_info(self, obj):
        t = obj.topic
        return {"id": t.id, "slug": t.slug, "title": t.title}
    
    def get_unlock_order(self, obj):
        return (obj.highest_completed_order or 0) + 1
        

class SpeakingPromptSerializer(serializers.ModelSerializer):
    class Meta:
        model = SpeakingPrompt
        fields = ["id", "text", "target", "tip"]
        read_only_fields = ["id"]

class SkillChoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = SkillChoice
        fields = ["id", "text", "is_correct"]
        read_only_fields = ["id"] 

class SkillQuestionSerializer(serializers.ModelSerializer):
    choices = SkillChoiceSerializer(many=True) 
    answer = serializers.CharField(write_only=True, required=False, allow_blank=False)

    class Meta:
        model = SkillQuestion
        fields = ["id", "question_text", "choices", "answer"]
        read_only_fields = ["id"]
    
    def validate(self, attrs):
        ans = attrs.get("answer")
        choices = attrs.get("choices", [])
        if ans:
            if not any(c.get("text") == ans for c in choices):
                raise serializers.ValidationError("`answer` phải trùng một lựa chọn trong `choices`.")
        else:
            if sum(1 for c in choices if c.get("is_correct")) != 1:
                raise serializers.ValidationError("Phải có đúng 1 lựa chọn `is_correct=True` nếu không gửi `answer`.")
        return attrs

# Serializer cho Fill in the Gap (điền khuyết)
class SkillGapSerializer(serializers.ModelSerializer):
    class Meta:
        model = SkillGap
        fields = ["id", "text", "answer"]
        read_only_fields = ["id"]

# Serializer cho Ordering (sắp xếp)
class OrderingItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderingItem
        fields = ["id", "text", "order_index"]
        read_only_fields = ["id"]

# Serializer cho Matching (ghép nối)
class MatchingPairSerializer(serializers.ModelSerializer):
    class Meta:
        model = MatchingPair
        fields = ["id", "left_text", "left_text_i18n", "right_text"]
        read_only_fields = ["id"]


# Serializer cho Listening (nghe)
class ListeningPromptSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListeningPrompt
        fields = ["id", "audio_url", "question_text", "answer"]
        read_only_fields = ["id"]

# Serializer cho Pronunciation (phát âm)
class PronunciationPromptSerializer(serializers.ModelSerializer):
    class Meta:
        model = PronunciationPrompt
        fields = ["id", "word", "phonemes", "answer"]
        read_only_fields = ["id"]


# Serializer cho Reading (đọc hiểu)
class ReadingQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReadingQuestion
        fields = ["id", "question_text", "answer"]
        read_only_fields = ["id"]

class ReadingContentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReadingContent
        fields = ["id", "passage"]
        read_only_fields = ["id"]

# Serializer cho Writing (viết)
class WritingQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = WritingQuestion
        fields = ["id", "prompt", "answer"]
        read_only_fields = ["id"]

# Serializer chính cho Skill
class SkillSerializer(serializers.ModelSerializer):
    # Tuỳ theo loại skill, bao gồm các trường lồng tương ứng. Chỉ trường phù hợp mới có dữ liệu, các trường khác sẽ là rỗng.
    quiz_questions = SkillQuestionSerializer(many=True, required=False)
    fillgaps = SkillGapSerializer(many=True, required=False)
    ordering_items = OrderingItemSerializer(many=True, required=False)
    matching_pairs = MatchingPairSerializer(many=True, required=False)
    listening_prompts = ListeningPromptSerializer(many=True, required=False)
    pronunciation_prompts = PronunciationPromptSerializer(many=True, required=False)
    reading_questions = ReadingQuestionSerializer(many=True, required=False)
    writing_questions = WritingQuestionSerializer(many=True, required=False)
    speaking_prompts = SpeakingPromptSerializer(many=True, required=False) 
    reading_content = ReadingContentSerializer(read_only=True)

    title_i18n = serializers.JSONField(required=False)
    description_i18n = serializers.JSONField(required=False, allow_null=True)

    class Meta:
        model = Skill
        fields = [
            "id", "title", "title_i18n", "description_i18n",
            "type", "xp_reward", "duration_seconds", "difficulty",
            "language_code", "tags", "is_active",
            "quiz_questions", "fillgaps", "ordering_items", "matching_pairs",
            "listening_prompts", "pronunciation_prompts",
            "reading_content", "reading_questions",
            "writing_questions", "speaking_prompts",
        ]
        read_only_fields = ["id"]

    def create(self, validated_data):
        quiz_data = validated_data.pop("quiz_questions", None)
        fillgap_data = validated_data.pop("fillgaps", None)
        ordering_data = validated_data.pop("ordering_items", None)
        matching_data = validated_data.pop("matching_pairs", None)
        listening_data = validated_data.pop("listening_prompts", None)
        pronunciation_data = validated_data.pop("pronunciation_prompts", None)
        reading_content_data = validated_data.pop("reading_content", None)
        reading_questions_data = validated_data.pop("reading_questions", None)
        speaking_data = validated_data.pop("speaking_prompts", None)
        writing_data = validated_data.pop("writing_questions", None)

        skill = Skill.objects.create(**validated_data)

        if skill.type == "quiz" and quiz_data is not None:
            for q_item in quiz_data:
                answer = q_item.pop("answer", None)          
                choices = q_item.pop("choices", [])          
                question = SkillQuestion.objects.create(skill=skill, **q_item)
                for choice in choices:
                    SkillChoice.objects.create(question=question, **choice)
                if answer:  # NEW: đánh dấu đúng theo answer
                    SkillChoice.objects.filter(question=question).update(is_correct=False)
                    SkillChoice.objects.filter(question=question, text=answer).update(is_correct=True)

        if skill.type == "fillgap" and fillgap_data is not None:
            for gap in fillgap_data:
                SkillGap.objects.create(skill=skill, **gap)

        if skill.type == "ordering" and ordering_data is not None:
            for item in ordering_data:
                OrderingItem.objects.create(skill=skill, **item)

        if skill.type == "matching" and matching_data is not None:
            for pair in matching_data:
                MatchingPair.objects.create(skill=skill, **pair)

        if skill.type == "listening" and listening_data is not None:
            for prompt in listening_data:
                ListeningPrompt.objects.create(skill=skill, **prompt)

        if skill.type == "pron" and pronunciation_data is not None:
            for prompt in pronunciation_data:
                PronunciationPrompt.objects.create(skill=skill, **prompt)

        if skill.type == "reading":
            if reading_content_data is not None:
                passage_text = reading_content_data if isinstance(reading_content_data, str) else str(reading_content_data)
                ReadingContent.objects.create(skill=skill, passage=passage_text)
            if reading_questions_data is not None:
                for q in reading_questions_data:
                    ReadingQuestion.objects.create(skill=skill, **q)

        if skill.type == "writing" and writing_data is not None:
            for q in writing_data:
                WritingQuestion.objects.create(skill=skill, **q)

        if skill.type == "speaking" and speaking_data is not None:  # NEW
            for sp in speaking_data:
                SpeakingPrompt.objects.create(skill=skill, **sp)

        return skill

    def update(self, instance, validated_data):
        instance.title = validated_data.get("title", instance.title)
        instance.is_active = validated_data.get("is_active", instance.is_active)

        new_type = validated_data.get("type", instance.type)
        if new_type and new_type != instance.type:
            instance.type = new_type
            instance.quiz_questions.all().delete()
            instance.fillgaps.all().delete()
            instance.ordering_items.all().delete()
            instance.matching_pairs.all().delete()
            instance.listening_prompts.all().delete()
            instance.pronunciation_prompts.all().delete()
            instance.reading_questions.all().delete()
            instance.writing_questions.all().delete()
            instance.speaking_prompts.all().delete()  # NEW
            ReadingContent.objects.filter(skill=instance).delete()
        instance.save()

        if "quiz_questions" in validated_data:
            quiz_data = validated_data.pop("quiz_questions")
            instance.quiz_questions.all().delete()
            for q_item in quiz_data:
                answer = q_item.pop("answer", None)         # NEW
                choices = q_item.pop("choices", [])
                question = SkillQuestion.objects.create(skill=instance, **q_item)
                for choice in choices:
                    SkillChoice.objects.create(question=question, **choice)
                if answer:
                    SkillChoice.objects.filter(question=question).update(is_correct=False)
                    SkillChoice.objects.filter(question=question, text=answer).update(is_correct=True)

        if "fillgaps" in validated_data:
            fillgap_data = validated_data.pop("fillgaps")
            instance.fillgaps.all().delete()
            for gap in fillgap_data:
                SkillGap.objects.create(skill=instance, **gap)

        if "ordering_items" in validated_data:
            ordering_data = validated_data.pop("ordering_items")
            instance.ordering_items.all().delete()
            for item in ordering_data:
                OrderingItem.objects.create(skill=instance, **item)

        if "matching_pairs" in validated_data:
            matching_data = validated_data.pop("matching_pairs")
            instance.matching_pairs.all().delete()
            for pair in matching_data:
                MatchingPair.objects.create(skill=instance, **pair)

        if "listening_prompts" in validated_data:
            listening_data = validated_data.pop("listening_prompts")
            instance.listening_prompts.all().delete()
            for prompt in listening_data:
                ListeningPrompt.objects.create(skill=instance, **prompt)

        if "pronunciation_prompts" in validated_data:
            pronunciation_data = validated_data.pop("pronunciation_prompts")
            instance.pronunciation_prompts.all().delete()
            for prompt in pronunciation_data:
                PronunciationPrompt.objects.create(skill=instance, **prompt)

        if instance.type == "reading":
            if "reading_content" in validated_data:
                passage_text = validated_data.pop("reading_content")
                ReadingContent.objects.filter(skill=instance).delete()
                if passage_text:
                    text = passage_text if isinstance(passage_text, str) else str(passage_text)
                    ReadingContent.objects.create(skill=instance, passage=text)
            if "reading_questions" in validated_data:
                reading_questions_data = validated_data.pop("reading_questions")
                instance.reading_questions.all().delete()
                for q in reading_questions_data:
                    ReadingQuestion.objects.create(skill=instance, **q)

        if instance.type == "writing" and "writing_questions" in validated_data:
            writing_data = validated_data.pop("writing_questions")
            instance.writing_questions.all().delete()
            for q in writing_data:
                WritingQuestion.objects.create(skill=instance, **q)

        if "speaking_prompts" in validated_data:  
            speaking_data = validated_data.pop("speaking_prompts")
            instance.speaking_prompts.all().delete()
            for sp in speaking_data:
                SpeakingPrompt.objects.create(skill=instance, **sp)

        return instance




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


class AddSkillIn(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=[c.value for c in Skill.SkillType],
        required=True,
        help_text="Skill type"
    )
    title = serializers.CharField(required=False, allow_blank=True, max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    content = serializers.DictField(required=False)  # phải là object JSON nếu gửi
    xp_reward = serializers.IntegerField(required=False, min_value=0, default=10)
    duration_seconds = serializers.IntegerField(required=False, min_value=1, default=90)
    difficulty = serializers.IntegerField(required=False, min_value=0, default=1)
    order = serializers.IntegerField(required=False, min_value=1)

    def validate(self, attrs):
        return attrs


class LessonLiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesson
        fields = ["id", "title", "order", "xp_reward", "duration_seconds", "content"]


class LessonWithSkillsSerializer(LessonLiteSerializer):
    skills = SkillSerializer(many=True, read_only=True)
    class Meta(LessonLiteSerializer.Meta):
        fields = LessonLiteSerializer.Meta.fields + ["skills"]


class RoleplayBlockWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoleplayBlock
        fields = [
            "section", "order", "role", "text",
            "extra", "audio_key", "tts_voice", "lang_hint", "is_active",
        ]

class RoleplayBlockReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoleplayBlock
        fields = [
            "id", "section", "order", "role", "text",
            "extra", "audio_key", "tts_voice", "lang_hint", "is_active",
            "created_at",
        ]

class RoleplayScenarioWriteSerializer(serializers.ModelSerializer):
    blocks = RoleplayBlockWriteSerializer(many=True, required=False)

    class Meta:
        model = RoleplayScenario
        fields = [
            "slug", "title", "description", "level", "order",
            "tags", "skill_tags", "is_active",
            "blocks",
        ]

    def _build_embedding_text(self, blocks):
        order_priority = {"background": 1, "instruction": 2, "dialogue": 3, "warmup": 4, "vocabulary": 5}
        parts = []
        for b in sorted(blocks, key=lambda x: (order_priority.get(x.get("section"), 9), x.get("order", 0))):
            parts.append(f"[{b.get('section')}#{b.get('order')}] {b.get('role') or '-'}: {b.get('text')}")
        return "\n".join(parts)

    @transaction.atomic
    def create(self, validated_data):
        blocks_data = validated_data.pop("blocks", [])
        embedding_text = self._build_embedding_text(blocks_data) if blocks_data else ""
        scenario = RoleplayScenario.objects.create(embedding_text=embedding_text, **validated_data)

        if blocks_data:
            RoleplayBlock.objects.bulk_create([
                RoleplayBlock(scenario=scenario, **b) for b in blocks_data
            ])
        return scenario

    @transaction.atomic
    def update(self, instance, validated_data):
        blocks_data = validated_data.pop("blocks", None)

        for k, v in validated_data.items():
            setattr(instance, k, v)

        if blocks_data is not None:
            instance.blocks.all().delete()
            RoleplayBlock.objects.bulk_create([
                RoleplayBlock(scenario=instance, **b) for b in blocks_data
            ])
            instance.embedding_text = self._build_embedding_text(blocks_data)

        instance.save()
        return instance

class RoleplayScenarioReadSerializer(serializers.ModelSerializer):
    blocks = RoleplayBlockReadSerializer(many=True, read_only=True)

    class Meta:
        model = RoleplayScenario
        fields = [
            "id", "slug", "title", "description", "level", "order",
            "tags", "skill_tags", "is_active",
            "embedding_text", "created_at", "updated_at",
            "blocks",
        ]


ROLE_CHOICES = [
    ("teacher", "Teacher"),
    ("student_a", "Student A"),
    ("student_b", "Student B"),
    ("narrator", "Narrator"),
]

class BlockLineSerializer(serializers.Serializer):
    role   = serializers.CharField(help_text="Vai nói (teacher | student_a | student_b | narrator).")
    block_id = serializers.CharField(help_text="UUID của block.", required=False)
    section  = serializers.CharField(required=False)
    order    = serializers.IntegerField(required=False)
    text     = serializers.CharField()

class AwaitUserSerializer(serializers.Serializer):
    block_id = serializers.CharField(help_text="UUID block mà người học cần nói.")
    role     = serializers.ChoiceField(choices=[c[0] for c in ROLE_CHOICES])
    order    = serializers.IntegerField()
    expected_hint = serializers.CharField(required=False, allow_blank=True)

class ScoreSerializer(serializers.Serializer):
    cosine  = serializers.FloatField()
    lexical = serializers.FloatField()
    passed  = serializers.BooleanField()

# -------- START --------
class RoleplayStartIn(serializers.Serializer):
    scenario = serializers.CharField(help_text="Slug hoặc UUID của Scenario.")
    role     = serializers.ChoiceField(
        choices=[c[0] for c in ROLE_CHOICES],
        help_text="Vai người học sẽ nhập vai (teacher | student_a | student_b | narrator).",
    )

class RoleplayStartOut(serializers.Serializer):
    session_id    = serializers.CharField()
    prologue      = BlockLineSerializer(many=True, help_text="BACKGROUND/INSTRUCTION/WARMUP theo đúng thứ tự.")
    ai_utterances = BlockLineSerializer(many=True, help_text="Các câu AI nói trước khi đến lượt người học.")
    await_user    = AwaitUserSerializer(allow_null=True)

# -------- SUBMIT --------
class RoleplaySubmitIn(serializers.Serializer):
    session_id = serializers.CharField(help_text="ID phiên tạo từ /start.")
    transcript = serializers.CharField(help_text="Văn bản chuyển từ giọng nói (Whisper).")

class RoleplaySubmitPassOut(serializers.Serializer):
    passed   = serializers.BooleanField(default=True)
    score    = ScoreSerializer()
    next_ai  = BlockLineSerializer(many=True, help_text="Các câu AI tiếp theo tới lượt người học kế tiếp.")
    await_user = AwaitUserSerializer(allow_null=True)
    finished  = serializers.BooleanField()

class RoleplaySubmitFailOut(serializers.Serializer):
    passed   = serializers.BooleanField(default=False)
    score    = ScoreSerializer()
    feedback = serializers.CharField()
    expected_example = serializers.CharField()


class LessonWithProgressSerializer(serializers.ModelSerializer):
    total_skills = serializers.IntegerField(read_only=True)
    completed_skills = serializers.IntegerField(read_only=True)
    progress_pct = serializers.FloatField(read_only=True)
    unlocked = serializers.BooleanField(read_only=True)
    required_pct = serializers.IntegerField(read_only=True, default=80)

    class Meta:
        model = Lesson
        fields = ["id", "title", "order", "xp_reward", "duration_seconds",
                  "content", "total_skills", "completed_skills",
                  "progress_pct", "unlocked", "required_pct"]