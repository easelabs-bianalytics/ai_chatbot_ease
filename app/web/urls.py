from django.urls import path

from web.views import LoginView, LogoutView, SessaoView

urlpatterns = [
    path("sessao/", SessaoView.as_view(), name="auth-sessao"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
]
