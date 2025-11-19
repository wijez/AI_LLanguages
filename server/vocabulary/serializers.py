from rest_framework import serializers
from vocabulary.models import (
   KnownWord , Translation, Word, Language, LearningInteraction, Mistake
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


class KnownWordSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnownWord
        fields = '__all__'
    
    def validate(self, attrs):
        enr = attrs.get("enrollment")
        w   = attrs.get("word")
        if enr and w and enr.language_id != w.language_id:
            raise serializers.ValidationError("Word phải cùng ngôn ngữ với LanguageEnrollment.")
        return attrs


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
    

class LearningInteractionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LearningInteraction
        fields = '__all__'


class MistakeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Mistake
        fields = '__all__'
        read_only_fields = ["user","enrollment","timestamp"]





