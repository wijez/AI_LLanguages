from rest_framework import serializers
from django.contrib.auth import authenticate
from users.models import (
    User, AccountSetting, AccountSwitch
)
from django.contrib.auth.password_validation import validate_password
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.exceptions import InvalidToken
from django.core.exceptions import ValidationError


class UserSerializer(serializers.ModelSerializer):
    class Meta: 
        model = User 
        fields = ('id', 'username', 'email', 'first_name', 'last_name', 'avatar', 'bio', 'is_active', 'is_staff', 'is_superuser', 'last_login', 'last_active', 'date_joined')
        read_only_fields = ('last_active', 'date_joined')
        


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

    def validate(self, attrs):
        username = (attrs.get("username") or "").strip()
        email = (attrs.get("email") or "").strip()
        password = attrs["password"] or ""

        if User.objects.filter(username=username).exists():
            raise serializers.ValidationError({"username": "Tên đăng nhập đã tồn tại."})

        if email and User.objects.filter(email=email).exists():
            raise serializers.ValidationError({"email": "Email đã được sử dụng."})
        try:
            validate_password(password)
        except ValidationError as e:
            raise serializers.ValidationError({"password": list(e.messages)})

        return attrs
        
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


# class LoginSerializer(serializers.Serializer):
#     username = serializers.CharField()
#     password = serializers.CharField(write_only=True)

#     def validate(self, data):
#         user = authenticate(username=data["username"], password=data["password"])
#         if not user:
#             raise serializers.ValidationError("Tên đăng nhập hoặc mật khẩu không chính xác.")
#         if not user.is_active:
#             raise serializers.ValidationError("Tài khoản của bạn chưa được xác thực. Vui lòng kiểm tra email.")
#         data["user"] = user
#         return data

class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        login = (data.get("username") or "").strip()
        password = data.get("password") or ""

        # Mặc định dùng đúng chuỗi người dùng nhập
        username_for_auth = login

        # Nếu người dùng nhập email -> map sang username để dùng authenticate mặc định
        if "@" in login:
            user_obj = User.objects.filter(email__iexact=login).first()
            if user_obj:
                username_for_auth = getattr(user_obj, User.USERNAME_FIELD, getattr(user_obj, "username", login))

        # Thử đăng nhập
        user = authenticate(username=username_for_auth, password=password)

        # Fallback: nếu nhập username nhưng sai hoa/thường, thử tìm username case-insensitive
        if not user and "@" not in login:
            user_obj = User.objects.filter(username__iexact=login).first()
            if user_obj:
                user = authenticate(username=user_obj.username, password=password)

        if not user:
            raise serializers.ValidationError("Tên đăng nhập hoặc mật khẩu không chính xác.")

        if not user.is_active:
            raise serializers.ValidationError("Tài khoản của bạn chưa được xác thực. Vui lòng kiểm tra email.")

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


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "avatar", "bio")


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = self.context["request"].user
        if not user.check_password(attrs["current_password"]):
            raise serializers.ValidationError({"current_password": "Mật khẩu hiện tại không đúng"})
        validate_password(attrs["new_password"], user)
        return attrs

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"]) 
        user.save(update_fields=["password"])
        return user


class CustomTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        
        # Lấy JTI từ refresh token mà client gửi lên
        refresh = self.token_class(attrs['refresh'])
        jti = refresh.get('jti')
        
        try:
            user = User.objects.get(id=refresh.get('user_id'))
        except User.DoesNotExist:
            raise InvalidToken("User không tồn tại")

        # So sánh JTI của token với JTI đang "active" của user
        if user.active_refresh_jti != jti:
            raise InvalidToken("Phiên đăng nhập không hợp lệ. Tài khoản này đã được đăng nhập từ một thiết bị khác.")
            
        return data