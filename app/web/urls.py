from django.urls import path

from web.views import (
    EntrarComCodigoView,
    LimitesView,
    LoginView,
    LogoutView,
    PasseioView,
    SessaoView,
    SolicitarCodigoView,
)

urlpatterns = [
    path("sessao/", SessaoView.as_view(), name="auth-sessao"),
    path("codigo/", SolicitarCodigoView.as_view(), name="auth-codigo"),
    path("entrar/", EntrarComCodigoView.as_view(), name="auth-entrar"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("limites/", LimitesView.as_view(), name="auth-limites"),
    path("passeio/", PasseioView.as_view(), name="auth-passeio"),
]
