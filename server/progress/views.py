from django.shortcuts import render
from rest_framework import viewsets
from progress.models import DailyXP
from progress.serializers import DailyXPSerializer


class DailyXPViewSet(viewsets.ModelViewSet):
    queryset = DailyXP.objects.all()
    serializer_class = DailyXPSerializer
    