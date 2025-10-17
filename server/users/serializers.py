from rest_framework import serializers
from django.contrib.auth import authenticate
from users.models import (
    User, AccountSetting, AccountSwitch
)
from django.contrib.auth.password_validation import validate_password


class UserSerializer(serializers.ModelSerializer):
    class Meta: 
        model = User 
        fields = '__all__'


class AccountSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountSetting
        fields = '__all__'


class AccountSwitchSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountSwitch
        fields = '__all__'


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ("username", "email", "password", "avatar", "bio")

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data["username"],
            email=validated_data.get("email"),
            password=validated_data["password"],
            avatar=validated_data.get("avatar", ""),
            bio=validated_data.get("bio", ""),
            is_active=False 
        )
        return user


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(username=data["username"], password=data["password"])
        if not user:
            raise serializers.ValidationError("Invalid credentials")
        if not user.is_active:
            raise serializers.ValidationError("Account not verified")
        data["user"] = user
        return data


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class VerifyCodeSerializer(serializers.Serializer):
    username = serializers.CharField()
    verify_code = serializers.CharField(max_length=6)


class ResendVerifyCodeSerializer(serializers.Serializer):
    username = serializers.CharField()


class UserMeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "avatar",
            "bio",
            "is_active",
            "is_staff",
            "is_superuser",
            "last_login",
            "last_active",
            "date_joined",
        )
        read_only_fields = fields