import random
import string
from rest_framework_simplejwt.tokens import RefreshToken

def generate_verify_code():
    # Sinh mã ngẫu nhiên 6 ký tự (chữ + số)
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {"refresh": str(refresh), "access": str(refresh.access_token)}