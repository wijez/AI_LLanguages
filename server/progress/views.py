from django.shortcuts import render
from django.utils import timezone
from rest_framework import viewsets
from progress.models import DailyXP
from progress.serializers import DailyXPSerializer
from django.http import FileResponse, Http404
from pathlib import Path
from django.conf import settings
from rest_framework import viewsets, permissions
from rest_framework.decorators import action

class DailyXPViewSet(viewsets.ModelViewSet):
    queryset = DailyXP.objects.all()
    serializer_class = DailyXPSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return DailyXP.objects.filter(user=self.request.user)


def serve_audio(request, path):
    file_path = Path(settings.MEDIA_ROOT) / path
    if not file_path.exists():
        raise Http404("Audio not found")
    return FileResponse(open(file_path, "rb"), content_type="audio/mpeg")