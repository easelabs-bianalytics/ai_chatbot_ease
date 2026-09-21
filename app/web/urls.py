from django.urls import path

from web.views import EntrarComCodigoView, LoginView, LogoutView, SessaoView, SolicitarCodigoView

urlpatterns = [
    path("sessao/", SessaoView.as_view(), name="auth-sessao"),
    path("codigo/", SolicitarCodigoView.as_view(), name="auth-codigo"),
    path("entrar/", EntrarComCodigoView.as_view(), name="auth-entrar"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
]
