from django.urls import path
from .views import RegisterView, LoginView, ForgotPasswordView, VerifyUserView, ResendVerifyCodeView

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("forgot-password/", ForgotPasswordView.as_view(), name="forgot-password"),
    path("verify-user/", VerifyUserView.as_view(), name="verify-user"),
    path("resend-verify-code/", ResendVerifyCodeView.as_view(), name="resend-verify-code"),
]
