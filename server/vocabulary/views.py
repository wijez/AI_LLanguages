from django.shortcuts import render
from rest_framework import viewsets
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from vocabulary.models import (
    AudioAsset,KnownWord , Translation, Word, WordRelation, LearningInteraction, Mistake
)

from vocabulary.serializers import (
    AudioAssetSerializer,KnownWordSerializer, TranslationSerializer,
    WordRelationSerializer, WordSerializer, LearningInteractionSerializer, MistakeSerializer
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

    def create(self, request, *args, **kwargs):
        many = isinstance(request.data, list)  # nếu gửi lên là list
        serializer = self.get_serializer(data=request.data, many=many)
        serializer.is_valid(raise_exception=True)
        instances = serializer.save()
        out = self.get_serializer(instances, many=many)
        return Response(out.data, status=status.HTTP_201_CREATED)


class WordViewSet(viewsets.ModelViewSet):
    queryset = Word.objects.all()
    serializer_class = WordSerializer

    def create(self, request, *args, **kwargs):
        many = isinstance(request.data, list)
        serializer = self.get_serializer(data=request.data, many=many)
        serializer.is_valid(raise_exception=True)
        instances = serializer.save()
        out = self.get_serializer(instances, many=many)
        return Response(out.data, status=status.HTTP_201_CREATED)

class WordRelationViewSet(viewsets.ModelViewSet):
    queryset = WordRelation.objects.all()
    serializer_class = WordRelationSerializer

    def create(self, request, *args, **kwargs):
        many = isinstance(request.data, list)
        serializer = self.get_serializer(data=request.data, many=many)
        serializer.is_valid(raise_exception=True)
        instances = serializer.save()
        out = self.get_serializer(instances, many=many)
        return Response(out.data, status=status.HTTP_201_CREATED)


class LearningInteractionViewSet(viewsets.ModelViewSet):
    queryset = LearningInteraction.objects.all()
    serializer_class = LearningInteractionSerializer


class MistakeViewSet(viewsets.ModelViewSet):
    queryset = Mistake.objects.all()
    serializer_class = MistakeSerializer


@api_view(['GET'])
def export_mistakes(request):
    qs = Mistake.objects.all().values("user_id", "enrollment_id", "score", "source", "timestamp")
    return Response(list(qs))
