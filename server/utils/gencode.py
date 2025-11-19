import random
import string
from rest_framework_simplejwt.tokens import RefreshToken

def generate_verify_code():
    # Sinh mã ngẫu nhiên 6 ký tự (chữ + số)
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    user.active_refresh_jti = refresh.get('jti') 
    user.save(update_fields=['active_refresh_jti'])
    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }