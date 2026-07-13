"""API for Navicat-style BLOB catalog browsing (PR1)."""
from __future__ import annotations

from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from images.blob_catalog_service import (
    BlobCatalogError,
    get_database_object_detail,
    list_catalog_connections,
    list_connection_databases,
    list_database_objects,
)
from utils.permissions import IsActiveAccount
from utils.responses import error_response, success_response


@extend_schema(tags=["blob-catalog"])
class BlobCatalogConnectionsView(APIView):
    """GET /api/images/blob-catalog/connections/ — list browsable database connections."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request):
        return success_response(list_catalog_connections())


@extend_schema(
    tags=["blob-catalog"],
    parameters=[
        OpenApiParameter(name="connection_id", type=int, required=False),
        OpenApiParameter(name="db_alias", type=str, required=False),
    ],
)
class BlobCatalogDatabasesView(APIView):
    """GET /api/images/blob-catalog/databases/ — list databases on a connection."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request):
        connection_id = request.query_params.get("connection_id")
        db_alias = request.query_params.get("db_alias")
        parsed_id = None
        if connection_id not in (None, ""):
            try:
                parsed_id = int(connection_id)
            except (TypeError, ValueError):
                return error_response("connection_id 无效", code=4001, status=400)
        if parsed_id is None and not db_alias:
            return error_response("请提供 connection_id 或 db_alias", code=4001, status=400)
        try:
            databases = list_connection_databases(connection_id=parsed_id, db_alias=db_alias)
        except BlobCatalogError as exc:
            return error_response(str(exc), code=4001, status=400)
        return success_response(
            {
                "connection_id": parsed_id,
                "db_alias": db_alias,
                "databases": databases,
            }
        )


@extend_schema(
    tags=["blob-catalog"],
    parameters=[
        OpenApiParameter(name="connection_id", type=int, required=False),
        OpenApiParameter(name="db_alias", type=str, required=False),
        OpenApiParameter(name="database", type=str, required=True),
        OpenApiParameter(name="object_type", type=str, required=False, description="table 或 view"),
    ],
)
class BlobCatalogObjectsView(APIView):
    """GET /api/images/blob-catalog/objects/ — list all tables/views in a database."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request):
        database = request.query_params.get("database")
        if not database:
            return error_response("database 不能为空", code=4001, status=400)
        connection_id = request.query_params.get("connection_id")
        db_alias = request.query_params.get("db_alias")
        object_type = request.query_params.get("object_type")
        parsed_id = None
        if connection_id not in (None, ""):
            try:
                parsed_id = int(connection_id)
            except (TypeError, ValueError):
                return error_response("connection_id 无效", code=4001, status=400)
        if parsed_id is None and not db_alias:
            return error_response("请提供 connection_id 或 db_alias", code=4001, status=400)
        try:
            payload = list_database_objects(
                database,
                connection_id=parsed_id,
                db_alias=db_alias,
                object_type=object_type,
            )
        except BlobCatalogError as exc:
            return error_response(str(exc), code=4001, status=400)
        return success_response(payload)


@extend_schema(
    tags=["blob-catalog"],
    parameters=[
        OpenApiParameter(name="connection_id", type=int, required=False),
        OpenApiParameter(name="db_alias", type=str, required=False),
        OpenApiParameter(name="database", type=str, required=True),
    ],
)
class BlobCatalogObjectDetailView(APIView):
    """GET /api/images/blob-catalog/objects/{name}/ — column detail for one table/view."""

    permission_classes = [IsAuthenticated, IsActiveAccount]

    def get(self, request, name: str):
        database = request.query_params.get("database")
        if not database:
            return error_response("database 不能为空", code=4001, status=400)
        connection_id = request.query_params.get("connection_id")
        db_alias = request.query_params.get("db_alias")
        parsed_id = None
        if connection_id not in (None, ""):
            try:
                parsed_id = int(connection_id)
            except (TypeError, ValueError):
                return error_response("connection_id 无效", code=4001, status=400)
        if parsed_id is None and not db_alias:
            return error_response("请提供 connection_id 或 db_alias", code=4001, status=400)
        try:
            payload = get_database_object_detail(
                database,
                name,
                connection_id=parsed_id,
                db_alias=db_alias,
            )
        except BlobCatalogError as exc:
            return error_response(str(exc), code=4001, status=400)
        return success_response(payload)
