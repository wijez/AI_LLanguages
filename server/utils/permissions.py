import hmac
from django.conf import settings
from rest_framework.permissions import BasePermission, SAFE_METHODS

class HasInternalApiKey(BasePermission):
    message = "Missing or invalid internal API key."

    def has_permission(self, request, view):
        key = request.headers.get("X-Internal-Api-Key")
        expected = getattr(settings, "INTERNAL_API_KEY", "")
        return bool(key) and bool(expected) and hmac.compare_digest(key, expected)



class IsAdminOrSuperAdmin(BasePermission):
    """
    - Ai cũng được phép với SAFE_METHODS (GET/HEAD/OPTIONS).
    - Method ghi (POST/PUT/PATCH/DELETE) chỉ cho phép khi:
        user.is_authenticated AND (user.is_superuser OR user.is_staff)
    """
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        return bool(
            user and user.is_authenticated and (user.is_superuser or user.is_staff)
        )

    def has_object_permission(self, request, view, obj):
        # Áp cùng logic cho từng object để nhất quán
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        return bool(
            user and user.is_authenticated and (user.is_superuser or user.is_staff)
        )


class CanMarkOwnNotificationRead(BasePermission):
    def has_object_permission(self, request, view, obj):
        return (
            request.user.is_authenticated
            and obj.user_id == request.user.id
        )