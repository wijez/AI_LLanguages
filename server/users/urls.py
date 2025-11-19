from django.urls import path
from .views import CustomTokenRefreshView, MeView, RegisterView, LoginView, ForgotPasswordView, VerifyUserView, ResendVerifyCodeView
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    # path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("token/refresh/", CustomTokenRefreshView.as_view(), name="token_refresh"),
    path("forgot-password/", ForgotPasswordView.as_view(), name="forgot-password"),
    path("verify-user/", VerifyUserView.as_view(), name="verify-user"),
    path("resend-verify-code/", ResendVerifyCodeView.as_view(), name="resend-verify-code"),
    path('me/',  MeView.as_view(), name="read-me"),
]
