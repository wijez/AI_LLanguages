from rest_framework import serializers
from social.services import push_notification
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
        read_only_fields = ['user', 'created_at']


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
    participants = serializers.PrimaryKeyRelatedField(
        many=True, queryset=User.objects.all(), write_only=True, required=False
    )
    class Meta:
        model = Notification
        fields = [
            "id",
            "type",
            "title",
            "body",
            "payload",
            "read_at",
            "created_at",
            "user",
            "participants",
        ]
        read_only_fields = ["user", "created_at"]

    def create(self, validated_data):
        participants = validated_data.pop("participants", [])
        # Nếu admin gửi nhiều user, tạo 1 thông báo cho từng user
        notifications = []
        if participants:
            for user in participants:
                notif = Notification.objects.create(user=user, **validated_data)
                notifications.append(notif)
            return notifications  # trả về list
        # Nếu không có participants → user hiện tại
        user = self.context["request"].user
        notif = Notification.objects.create(user=user, **validated_data)
        push_notification(notif)
        return notif