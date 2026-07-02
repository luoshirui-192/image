"""Project-level views."""
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from config.readiness import collect_readiness
from utils.responses import success_response


class HealthView(APIView):
    """GET /api/health/ — service and production readiness check."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        from django.conf import settings

        readiness = collect_readiness()
        payload = {
            "service": "image-path-db-backend",
            "version": "1.0.0",
            "db_engine": settings.DB_ENGINE,
            "upload_root": settings.UPLOAD_ROOT,
            "debug": settings.DEBUG,
            "readiness": readiness,
        }
        return success_response(payload, message="ok")
