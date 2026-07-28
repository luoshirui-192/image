"""Request middleware for image/DB integrity."""
from __future__ import annotations


class RepairSystemDatabaseMiddleware:
    """Ensure default/legacy DB NAME was not left pointing at a catalog schema."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from images.external_db_service import ensure_system_database_names

        ensure_system_database_names()
        return self.get_response(request)
