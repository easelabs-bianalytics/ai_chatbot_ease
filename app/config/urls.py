from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView

from config.views import HealthView
from web.views import IndexView
from whatsapp.views import conexao

urlpatterns = [
    # O Admin tem tela de senha própria, e ela seria uma porta de entrada
    # sem e-mail da empresa. Quem vai ao Admin entra pelo código, como todo
    # mundo, e volta para lá; o Admin reconhece a mesma sessão.
    path("admin/login/", RedirectView.as_view(url="/?proximo=/admin/", query_string=False)),
    path("admin/whatsapp/conexao/", conexao, name="whatsapp-conexao"),
    path("admin/", admin.site.urls),
    path("api/health/", HealthView.as_view(), name="health"),
    path("api/auth/", include("web.urls")),
    path("api/whatsapp/", include("whatsapp.urls")),
    path("api/", include("messaging.urls")),
    path("", IndexView.as_view(), name="index"),
    # Rotas do próprio app: um F5 em /conversas/12 precisa devolver a página.
    re_path(r"^conversas(?:/\d+)?/?$", IndexView.as_view(), name="index-conversa"),
]
