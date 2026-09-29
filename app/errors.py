from __future__ import annotations

from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details

    def to_response(self) -> JSONResponse:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            payload["details"] = self.details
        return JSONResponse(status_code=self.status_code, content={"error": payload})


def not_found(message: str = "not found") -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, "not_found", message)


def bad_request(message: str, details: Any = None) -> ApiError:
    return ApiError(status.HTTP_400_BAD_REQUEST, "bad_request", message, details)


def unauthorized(message: str = "authentication required") -> ApiError:
    return ApiError(status.HTTP_401_UNAUTHORIZED, "unauthorized", message)


def forbidden(message: str = "forbidden") -> ApiError:
    return ApiError(status.HTTP_403_FORBIDDEN, "forbidden", message)


def upstream_error(code: str, message: str, status_code: int = 502) -> ApiError:
    return ApiError(status_code, code, message)
