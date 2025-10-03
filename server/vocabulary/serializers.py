from rest_framework import serializers
from vocabulary.models import (
    AudioAsset,KnownWord , Translation, Word, WordRelation, Language, LearningInteraction, Mistake
)

class WordListSerializer(serializers.ListSerializer):
    """
    Custom ListSerializer để xử lý batch insert:
    - Nếu từ đã tồn tại (theo language, text) → bỏ qua
    """
    def create(self, validated_data):
        instances = []
        for item in validated_data:
            lang = item["language"]  # instance Language do SlugRelatedField map sẵn
            text = item["text"]

            defaults = {
                "normalized": item.get("normalized", text.lower()),
                "part_of_speech": item.get("part_of_speech", ""),
            }

            obj, created = Word.objects.get_or_create(
                language=lang,
                text=text,
                defaults=defaults
            )
            if created:  # chỉ thêm nếu mới
                instances.append(obj)
        return instances


class AudioAssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = AudioAsset
        fields = '__all__'


class KnownWordSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnownWord
        fields = '__all__'


class TranslationSerializer(serializers.ModelSerializer):
    source_language = serializers.SlugRelatedField(
        slug_field="abbreviation", queryset=Language.objects.all()
    )
    target_language = serializers.SlugRelatedField(
        slug_field="abbreviation", queryset=Language.objects.all()
    )

    class Meta:
        model = Translation
        fields = '__all__'


class WordSerializer(serializers.ModelSerializer):
    language = serializers.SlugRelatedField(
        slug_field='abbreviation', 
        queryset=Language.objects.all()
    )
    class Meta:
        model = Word
        fields = '__all__'
        validators = []
        list_serializer_class = WordListSerializer
    


class WordRelationSerializer(serializers.ModelSerializer):
    language = serializers.SlugRelatedField(
        slug_field="abbreviation",
        queryset=Language.objects.all(),
        write_only=True
    )
    word_text = serializers.CharField(write_only=True)
    related_text = serializers.CharField(write_only=True)

    text = serializers.CharField(source="related.text", read_only=True)
    normalized = serializers.CharField(source="related.normalized", read_only=True)
    part_of_speech = serializers.CharField(source="related.part_of_speech", read_only=True)

    class Meta:
        model = WordRelation
        fields = ["relation_type", "language", "word_text", "related_text",
                  "text", "normalized", "part_of_speech"]

    def create(self, validated_data):
        lang = validated_data.pop("language")
        word_text = validated_data.pop("word_text").lower()
        related_text = validated_data.pop("related_text").lower()
        rel_type = validated_data.get("relation_type", "")

        try:
            word = Word.objects.get(language=lang, normalized=word_text)
            related = Word.objects.get(language=lang, normalized=related_text)
        except Word.DoesNotExist:
            raise serializers.ValidationError("Word hoặc related không tồn tại trong DB.")

        relation, _ = WordRelation.objects.get_or_create(
            word=word,
            related=related,
            relation_type=rel_type
        )
        return relation

class LearningInteractionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LearningInteraction
        fields = '__all__'


class MistakeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Mistake
        fields = '__all__'


class WordDetailSerializer(serializers.ModelSerializer):
    language = serializers.SlugRelatedField(
        slug_field="abbreviation",
        read_only=True
    )
    relations = WordRelationSerializer(many=True, read_only=True)

    class Meta:
        model = Word
        fields = ["id", "language", "text", "normalized", "part_of_speech", "relations"]


