from rest_framework import serializers
from vocabulary.models import (
    AudioAsset,KnownWord , Translation, Word, WordRelation, Language, LearningInteraction, Mistake
)

class AudioAssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = AudioAsset
        fields = '__all__'


class KnownWordSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnownWord
        fields = '__all__'


class TranslationSerializer(serializers.ModelSerializer):
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


class WordRelationSerializer(serializers.ModelSerializer):
    class Meta:
        model = WordRelation
        fields = '__all__'


class LearningInteractionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LearningInteraction
        fields = '__all__'


class MistakeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Mistake
        fields = '__all__'