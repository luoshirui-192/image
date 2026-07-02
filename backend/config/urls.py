"""URL configuration."""
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from config.settings_views import SystemConfigView
from config.views import HealthView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", HealthView.as_view(), name="health"),
    path("api/config/", SystemConfigView.as_view(), name="system-config"),
    path("api/auth/", include("users.urls")),
    path("api/images/", include("images.urls")),
    path("api/sql/", include("sqlquery.urls")),
    path("api/logs/", include("logs.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
