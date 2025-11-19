from django.conf import settings
from django.core.mail import send_mail


EMAIL_MESSAGE_TEMPLATES = {
    "verify_code": (
        "Xin chào {username},\n\n"
        "Mã xác thực (verify code) của bạn là: {verify_code}\n\n"
        "Aivory Team."
    ),
    "friend_request": (
        "Xin chào {username},\n\n"
        "{from_username} vừa gửi cho bạn một lời mời kết bạn trên Aivory.\n\n"
        "Aivory Team."
    ),
}
