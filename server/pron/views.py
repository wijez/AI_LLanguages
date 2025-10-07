from django.shortcuts import render

from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.response import Response

from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample, OpenApiTypes

from chat.models import Conversation
from .models import TargetUtterance, PronunciationAttempt
from .serializers import PronScoreRequestSerializer, PronAttemptSerializer, TargetSerializer
from .scoring import score_audio_stub

class PronScoreAPIView(APIView):
    """
    POST /api/pron/score/
    multipart/form-data:
      - audio: file
      - target_id (optional)
      - target_text (optional)
      - conversation_id (optional)
      - language_code (optional, default='en')
    """
    authentication_classes = []
    permission_classes = [] 

    @extend_schema(
        request=PronScoreRequestSerializer,
        responses={
            201: {
                'type': 'object',
                'properties': {
                    'attempt_id': {'type': 'string'},
                    'target': {
                        'type': 'object',
                        'properties': {
                            'id': {'type': 'string', 'nullable': True},
                            'text': {'type': 'string'},
                            'ipa': {'type': 'string'},
                            'language_code': {'type': 'string'}
                        }
                    },
                    'scores': {
                        'type': 'object',
                        'properties': {
                            'overall': {'type': 'number'},
                            'accuracy': {'type': 'number'},
                            'fluency': {'type': 'number'},
                            'completeness': {'type': 'number'}
                        }
                    },
                    'words': {'type': 'array', 'items': {'type': 'object'}},
                    'suggestions': {'type': 'array', 'items': {'type': 'string'}}
                }
            }
        },
        examples=[
            OpenApiExample(
                'Example Request',
                value={
                    'audio': '<binary_file>',
                    'target_text': 'Hello world',
                    'language_code': 'en'
                },
                request_only=True
            ),
            OpenApiExample(
                'Example Response',
                value={
                    'attempt_id': '123e4567-e89b-12d3-a456-426614174000',
                    'target': {
                        'id': None,
                        'text': 'Hello world',
                        'ipa': 'həˈloʊ wɜːrld',
                        'language_code': 'en'
                    },
                    'scores': {
                        'overall': 0.85,
                        'accuracy': 0.9,
                        'fluency': 0.8,
                        'completeness': 0.85
                    },
                    'words': [
                        {'word': 'Hello', 'score': 0.9, 'ipa': 'həˈloʊ'},
                        {'word': 'world', 'score': 0.8, 'ipa': 'wɜːrld'}
                    ],
                    'suggestions': [
                        'Try to pronounce the "r" in "world" more clearly',
                        'Pay attention to the vowel sound in "Hello"'
                    ]
                },
                response_only=True
            )
        ]
    )
    def post(self, request, *args, **kwargs):
        s = PronScoreRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data

        target = None
        target_text = v.get('target_text', '')
        if v.get('target_id'):
            target = get_object_or_404(TargetUtterance, id=v['target_id'])
            target_text = target.text

        conv = None
        if v.get('conversation_id'):
            conv = get_object_or_404(Conversation, id=v['conversation_id'])

        audio_file = v['audio']
        lang = v.get('language_code','en')

        scores, words, suggestions = score_audio_stub(audio_file, target_text, lang=lang)

        attempt = PronunciationAttempt.objects.create(
            conversation=conv,
            target=target,
            target_text=target_text if not target else '',
            language_code=lang,
            audio=audio_file,
            scores=scores,
            words=words,
            suggestions=suggestions
        )

        resp = {
            "attempt_id": str(attempt.id),
            "target": TargetSerializer(target).data if target else {
                "id": None, "text": target_text, "ipa": "", "language_code": lang
            },
            "scores": scores,
            "words": words,
            "suggestions": suggestions
        }
        return Response(resp, status=status.HTTP_201_CREATED)