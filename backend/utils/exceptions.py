"""Global DRF exception handler integrating Step 9 security errors."""
from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler as drf_exception_handler

from utils.file_security import AccessDeniedError, FileSecurityError, PathSecurityError, UploadValidationError
from utils.responses import error_response
from utils.sql_validator import SqlValidationError


def custom_exception_handler(exc, context):
    if isinstance(exc, UploadValidationError):
        return error_response(str(exc), code=4001, status=status.HTTP_400_BAD_REQUEST)
    if isinstance(exc, SqlValidationError):
        return error_response(str(exc), code=4001, status=status.HTTP_400_BAD_REQUEST)
    if isinstance(exc, PathSecurityError):
        return error_response(str(exc), code=4003, status=status.HTTP_403_FORBIDDEN)
    if isinstance(exc, AccessDeniedError):
        return error_response(str(exc), code=4001, status=status.HTTP_403_FORBIDDEN)
    if isinstance(exc, FileSecurityError):
        return error_response(str(exc), code=4003, status=status.HTTP_403_FORBIDDEN)

    response = drf_exception_handler(exc, context)
    if response is not None:
        message = str(exc.detail) if hasattr(exc, "detail") else str(exc)
        if isinstance(exc.detail, dict):
            message = "; ".join(
                f"{k}: {v[0] if isinstance(v, list) else v}" for k, v in exc.detail.items()
            )
        elif isinstance(exc.detail, list):
            message = str(exc.detail[0])

        http_status = response.status_code
        code = http_status
        if isinstance(exc, APIException) and hasattr(exc, "default_code"):
            code = http_status

        response.data = {"code": code, "message": message, "data": None}
        return response

    return response
