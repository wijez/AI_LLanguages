from dataclasses import field
from rest_framework import serializers
from ..users.models import (
    User, AccountSetting, AccountSwitch
)


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
