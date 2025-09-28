from django.conf import settings
from django.core.mail import send_mail


def send_verify_email(user, subject="Verify your account"):
    """Hàm gửi verify_code qua email"""
    if not user.email:
        return

    message = f"Xin chào {user.username},\n\nMã xác thực (verify code) của bạn là: {user.verify_code}\n\nDATN Team."
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )