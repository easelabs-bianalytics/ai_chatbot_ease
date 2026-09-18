from django.contrib import admin
from django.urls import include, path, re_path

from config.views import HealthView
from web.views import IndexView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", HealthView.as_view(), name="health"),
    path("api/auth/", include("web.urls")),
    path("api/", include("messaging.urls")),
    path("", IndexView.as_view(), name="index"),
    # Rotas do próprio app: um F5 em /conversas/12 precisa devolver a página.
    re_path(r"^conversas(?:/\d+)?/?$", IndexView.as_view(), name="index-conversa"),
]
