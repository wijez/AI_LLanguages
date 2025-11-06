from rest_framework import serializers
from social.models import (
    Friend, CalendarEvent, LeaderboardEntry
)

class FriendSerializer(serializers.ModelSerializer):
    class Meta:
        model = Friend
        fields = '__all__'


class CalendarEventSerializer(serializers.ModelSerializer):
    class Meta: 
        model = CalendarEvent
        fields = '__all__'


class LeaderboardEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaderboardEntry
        fields = '__all__'