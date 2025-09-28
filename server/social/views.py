from django.shortcuts import render
from rest_framework import viewsets
from social.serializers import (
    CalendarEventSerializer, FriendSerializer, LeaderboardEntrySerializer
)
from social.models import (
    Friend, CalendarEvent, LeaderboardEntry
)

class FriendViewSet(viewsets.ModelViewSet):
    queryset = Friend.objects.all()
    serializer_class = FriendSerializer


class CalendarEventSerializer(viewsets.ModelViewSet):
    queryset = CalendarEvent.objects.all()
    serializer_class = CalendarEventSerializer


class LeaderboardEntrySerialzer(viewsets.ModelViewSet):
    queryset = LeaderboardEntry.objects.all()
    serializer_class = LeaderboardEntrySerializer