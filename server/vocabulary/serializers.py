from rest_framework import serializers
from vocabulary.models import (
    AudioAsset,KnownWord , Translation, Word, WordRelation
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
    class Meta:
        model = Word
        fields = '__all__'


class WordRelationSerializer(serializers.ModelSerializer):
    class Meta:
        model = WordRelation
        fields = '__all__'