from rest_framework import serializers
from social.models import (
    Friend, CalendarEvent, LeaderboardEntry, Badge, UserBadge, Notification
)
from users.models import User

class UserBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "email")


class FriendSerializer(serializers.ModelSerializer):
    from_user = UserBriefSerializer(read_only=True)
    to_user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all()
    )

    class Meta:
        model = Friend
        fields = (
            "id",
            "from_user",
            "to_user",
            "accepted",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "from_user",
            "accepted",
            "created_at",
            "updated_at",
        )


class CalendarEventSerializer(serializers.ModelSerializer):
    class Meta: 
        model = CalendarEvent
        fields = '__all__'


class LeaderboardEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaderboardEntry
        fields = '__all__'


class BadgeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Badge
        fields = "__all__"

class UserBadgeSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserBadge
        fields = "__all__"

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = "__all__"