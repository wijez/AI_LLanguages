from re import I
from django.shortcuts import render
from rest_framework import viewsets
from rest_framework import status, generics
from rest_framework.response import Response
from django.core.mail import send_mail
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework.views import APIView
from utils.gencode import generate_verify_code, get_tokens_for_user
from drf_spectacular.utils import extend_schema
from utils.send_mail import send_verify_email

from users.models import (
    User, AccountSetting, AccountSwitch
)

from users.serializers import (
    UserMeSerializer, UserSerializer, AccountSettingSerializer, AccountSwitchSerializer, RegisterSerializer,
    VerifyCodeSerializer, ResendVerifyCodeSerializer, LoginSerializer, ForgotPasswordSerializer
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


@extend_schema(
    request=RegisterSerializer,
    responses={201: RegisterSerializer},
    description="Đăng ký tài khoản mới. User sẽ nhận verify_code để xác thực."
)
class RegisterView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        send_verify_email(user, subject="Đăng ký tài khoản - Verify Code")
        return Response({
            "message": "User registered. Please verify your account.",
            "verify_code": user.verify_code  # ⚠️ chỉ để test
        }, status=status.HTTP_201_CREATED)


@extend_schema(
    request=LoginSerializer,
    responses={200: dict},
    description="Đăng nhập hệ thống, trả về JWT token."
)
class LoginView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        tokens = get_tokens_for_user(user)
        return Response({
            "message": "Login successful",
            "tokens": tokens
        }, status=status.HTTP_200_OK)



@extend_schema(
    request=ForgotPasswordSerializer,
    responses={200: dict},
    description="Gửi mã xác thực về email để đặt lại mật khẩu."
)
class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"detail": "User with this email not found"}, status=status.HTTP_404_NOT_FOUND)

        # sinh mã mới
        user.verify_code = generate_verify_code()
        user.save()
        send_verify_email(user, subject="Quên mật khẩu - Verify Code")
        return Response({
            "message": "Verify code sent to your email (demo only)",
            "verify_code": user.verify_code
        }, status=status.HTTP_200_OK)


@extend_schema(
    request=VerifyCodeSerializer,
    responses={200: dict},
    description="Xác thực user bằng verify_code."
)
class VerifyUserView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = VerifyCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        username = serializer.validated_data["username"]
        code = serializer.validated_data["verify_code"]

        try:
            user = User.objects.get(username=username, verify_code=code)
        except User.DoesNotExist:
            return Response({"detail": "Invalid code or user"}, status=status.HTTP_400_BAD_REQUEST)

        user.verify_code = None
        user.is_active = True
        user.save()

        return Response({"message": "User verified successfully"}, status=status.HTTP_200_OK)


@extend_schema(
    request=ResendVerifyCodeSerializer,
    responses={200: dict},
    description="Gửi lại verify_code cho user."
)
class ResendVerifyCodeView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = ResendVerifyCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        username = serializer.validated_data["username"]

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            return Response({"detail": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        user.verify_code = generate_verify_code()
        user.save()
        send_verify_email(user, subject="Gửi lại Verify Code")
        return Response({
            "message": "Verify code resent successfully",
            "verify_code": user.verify_code
        }, status=status.HTTP_200_OK)


class MeView(APIView):
    permission_classes = [IsAuthenticated]
    @extend_schema(responses=UserMeSerializer)
    def get(self, request):
        return Response(UserMeSerializer(request.user, context={"request": request}).data)