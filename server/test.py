from django.core.mail import send_mail
from django.conf import settings

def send_test_email():
    send_mail(
        subject="Test Email from Django",
        message="Hello, this is a test email.",
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=["viet.info.43@gmail.com"],
        fail_silently=False,
    )
