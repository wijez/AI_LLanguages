from django.shortcuts import render
from rest_framework import viewsets
from vocabulary.models import (
    AudioAsset,KnownWord , Translation, Word, WordRelation
)

from vocabulary.serializers import (
    AudioAssetSerializer,KnownWordSerializer, TranslationSerializer,
    WordRelationSerializer, WordSerializer
)

class AudioAssetViewSet(viewsets.ModelViewSet):
    queryset = AudioAsset.objects.all()
    serializer_class = AudioAssetSerializer


class KnownWordViewSet(viewsets.ModelViewSet):
    queryset = KnownWord.objects.all()
    serializer_class = KnownWordSerializer


class TranslationViewSet(viewsets.ModelViewSet):
    queryset = Translation.objects.all()
    serializer_class = TranslationSerializer


class WordViewSet(viewsets.ModelViewSet):
    queryset = Word.objects.all()
    serializer_class = WordSerializer


class WordRelationViewSet(viewsets.ModelViewSet):
    queryset = WordRelation.objects.all()
    serializer_class = WordRelationSerializer