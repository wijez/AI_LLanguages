import jwt
from datetime import datetime, timezone
from types import SimpleNamespace

from django.conf import settings
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework import exceptions


class BEJWTUser(SimpleNamespace):
    """
    User "ảo" đại diện cho user bên BE.
    Chỉ cần có id, username, và is_authenticated là đủ cho DRF.
    """
    @property
    def is_authenticated(self) -> bool:
        return True


class BEJWTAuthentication(BaseAuthentication):
    """
    Xác thực bằng JWT do BE phát hành.
    - BE ký token bằng SECRET_KEY của BE (HS256).
    - AI giải mã bằng settings.BE_JWT_SECRET.
    - Không load user từ DB AI, chỉ tạo BEJWTUser.
    """

    keyword = b"bearer"

    def authenticate(self, request):
        auth = get_authorization_header(request).split()

        if not auth or auth[0].lower() != self.keyword:
            return None  # Không truyền Bearer -> cho các auth khác xử lý

        if len(auth) == 1:
            raise exceptions.AuthenticationFailed("Invalid Authorization header. No credentials provided.")
        elif len(auth) > 2:
            raise exceptions.AuthenticationFailed("Invalid Authorization header format.")

        token = auth[1]

        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
        except jwt.ExpiredSignatureError:
            raise exceptions.AuthenticationFailed("Token has expired.")
        except jwt.InvalidTokenError:
            raise exceptions.AuthenticationFailed("Invalid token.")

        # Kiểm tra exp (nếu SimpleJWT của BE có set)
        exp = payload.get("exp")
        if exp:
            now = datetime.now(timezone.utc).timestamp()
            if now > exp:
                raise exceptions.AuthenticationFailed("Token has expired.")

        user_id = payload.get("user_id")
        if not user_id:
            raise exceptions.AuthenticationFailed("Token missing 'user_id' claim.")

        username = payload.get("username") or payload.get("email") or f"user-{user_id}"
        is_staff = payload.get("is_staff", False)
        is_superuser = payload.get("is_superuser", False)

        user = BEJWTUser(
            id=user_id,
            username=username,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )

        return (user, token)
