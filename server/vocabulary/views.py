from django.shortcuts import render
from rest_framework import viewsets
from rest_framework import status
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from utils.permissions import HasInternalApiKey
from vocabulary.models import (
    KnownWord , Translation, Word, LearningInteraction, Mistake
)

from vocabulary.serializers import (
    KnownWordSerializer, TranslationSerializer,
    WordSerializer, LearningInteractionSerializer, MistakeSerializer
)
from django.utils import timezone
from django.db.models import Q
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status




class KnownWordViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = KnownWord.objects.all()
    serializer_class = KnownWordSerializer

    @action(detail=False, methods=['get'])
    def due(self, request):
        """Danh sách từ đến hạn ôn cho 1 enrollment"""
        enrollment_id = request.query_params.get("enrollment")
        limit = int(request.query_params.get("limit", 50))
        if not enrollment_id:
            return Response({"detail": "Missing enrollment"}, status=400)
        qs = (self.queryset
              .filter(enrollment_id=enrollment_id)
              .filter(Q(next_review__lte=timezone.now()) | Q(next_review__isnull=True))
              .order_by('next_review')[:limit])
        return Response(self.get_serializer(qs, many=True).data)

    @action(detail=True, methods=['post'])
    def review(self, request, pk=None):
        """Cập nhật SRS: nhận {quality:0..5} hoặc {correct:bool}; ghi LearningInteraction"""
        kw = self.get_object()
        quality = request.data.get("quality")
        correct = request.data.get("correct")
        if quality is None and correct is None:
            return Response({"detail": "Provide quality or correct"}, status=400)

        # cập nhật SRS
        if quality is not None:
            kw.calculate_next_review(int(quality))
            success = int(quality) >= 3
            value = float(quality)
        else:
            kw.review(bool(correct))
            success = bool(correct)
            value = 1.0 if success else 0.0

        # log tương tác học (review_word)
        LearningInteraction.objects.create(
            user=kw.enrollment.user,
            enrollment=kw.enrollment,
            word=kw.word,
            action="review_word",
            value=value,
            success=success,
            meta=request.data,
        )
        return Response(self.get_serializer(kw).data, status=200)

    @action(detail=True, methods=['post'])
    def reset(self, request, pk=None):
        kw = self.get_object()
        kw.reset()
        return Response(self.get_serializer(kw).data, status=200)

    @action(detail=False, methods=['post'])
    def touch(self, request):
        """
        get_or_create KnownWord cho (enrollment, word).
        Body: {enrollment: id, word: id} (khuyên dùng), hoặc {enrollment, language:'en', word_text:'hello'}
        """
        from languages.models import Language
        enrollment_id = request.data.get("enrollment")
        word_id = request.data.get("word")
        word_text = request.data.get("word_text")
        lang_abbr = request.data.get("language")

        if not enrollment_id:
            return Response({"detail": "Missing enrollment"}, status=400)

        if word_id:
            from vocabulary.models import Word
            try:
                w = Word.objects.get(id=word_id)
            except Word.DoesNotExist:
                return Response({"detail":"Word not found"}, status=404)
        else:
            if not (word_text and lang_abbr):
                return Response({"detail":"Provide (word) or (word_text & language)"}, status=400)
            try:
                lang = Language.objects.get(abbreviation=lang_abbr)
            except Language.DoesNotExist:
                return Response({"detail":"Language not found"}, status=404)
            from vocabulary.models import Word
            w, _ = Word.objects.get_or_create(
                language=lang, text=word_text,
                defaults={"normalized": word_text.lower(), "part_of_speech": ""}
            )

        kw, _ = KnownWord.objects.get_or_create(enrollment_id=enrollment_id, word=w)
        # chặn sai ngôn ngữ
        if kw.enrollment.language_id != w.language_id:
            return Response({"detail":"Word phải cùng ngôn ngữ với LanguageEnrollment."}, status=400)
        return Response(self.get_serializer(kw).data, status=200)


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


class LearningInteractionViewSet(viewsets.ModelViewSet):
    permission_classes = [HasInternalApiKey | IsAuthenticated]
    queryset = LearningInteraction.objects.all()
    serializer_class = LearningInteractionSerializer


class MistakeViewSet(viewsets.ModelViewSet):
    permission_classes = [HasInternalApiKey | IsAuthenticated]
    queryset = Mistake.objects.all().order_by('-timestamp')
    serializer_class = MistakeSerializer
    filterset_fields = ['skill','lesson','enrollment','source']
    ordering_fields = ['timestamp','id']

@api_view(['GET'])
def export_mistakes(request):
    qs = Mistake.objects.all().values("user_id", "enrollment_id", "score", "source", "timestamp")
    return Response(list(qs))
