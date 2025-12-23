from django.shortcuts import render
from rest_framework import viewsets
from progress.models import DailyXP
from progress.serializers import DailyXPSerializer
from django.http import FileResponse, Http404
from pathlib import Path
from django.conf import settings


class DailyXPViewSet(viewsets.ModelViewSet):
    queryset = DailyXP.objects.all()
    serializer_class = DailyXPSerializer
    

def serve_audio(request, path):
    file_path = Path(settings.MEDIA_ROOT) / path
    if not file_path.exists():
        raise Http404("Audio not found")
    return FileResponse(open(file_path, "rb"), content_type="audio/mpeg")