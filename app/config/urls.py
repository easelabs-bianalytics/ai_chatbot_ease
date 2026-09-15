from django.contrib import admin
from django.urls import include, path

from config.views import HealthView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", HealthView.as_view(), name="health"),
    path("api/", include("messaging.urls")),
]
