"""Auth routes — Step 11."""
from django.urls import path

from users.views import LoginView, MeView, TokenRefreshView

urlpatterns = [
    path("login/", LoginView.as_view(), name="auth-login"),
    path("me/", MeView.as_view(), name="auth-me"),
    path("refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
]
