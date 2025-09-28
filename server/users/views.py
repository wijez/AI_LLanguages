from django.shortcuts import render
from rest_framework import viewsets

from ..users.models import (
    User, AccountSetting, AccountSwitch
)

from ..users.serializers import (
    UserSerializer, AccountSettingSerializer, AccountSwitchSerializer
)


class UserViewset(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer


class AccountSettingViewset(viewsets.ModelViewSet):
    queryset = AccountSetting.objects.all()
    serializer_class = AccountSettingSerializer


class AccountSwitchViewset(viewsets.ModelViewSet):
    queryset = AccountSwitch.objects.all()
    serializer_class = AccountSwitchSerializer

