from django.conf import settings
from django.core.mail import send_mail

from utils.email import EMAIL_MESSAGE_TEMPLATES


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

def send_user_email(user, template_key, subject, **context):
    if not getattr(user, "email", None):
        return

    template = EMAIL_MESSAGE_TEMPLATES.get(template_key)
    if not template:
        raise ValueError(f"Unknown email template: {template_key}")

    base_ctx = {
        "username": getattr(user, "username", "") or getattr(user, "email", ""),
        "verify_code": getattr(user, "verify_code", ""),
    }
    base_ctx.update(context or {})

    message = template.format(**base_ctx)

    send_mail(
        subject=subject,
        message=message,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[user.email],
        fail_silently=False,
    )
