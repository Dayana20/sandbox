import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.core.config import settings
from app.errors import (
    FileConflictError,
    FileNotFoundError,
    IdempotencyError,
    InvalidRequestError,
    PermissionDeniedError,
    ProviderError,
    StorageError,
    StorageNotConfiguredError,
)


logger = logging.getLogger(__name__)
request_logger = logging.getLogger("app.requests")

REQUEST_ID_HEADER = "X-Request-ID"

# Every error the API returns: exception -> (HTTP status, error code)
ERRORS: dict[type[StorageError], tuple[int, str]] = {
    InvalidRequestError: (400, "invalid_request"),
    PermissionDeniedError: (403, "permission_denied"),
    FileNotFoundError: (404, "not_found"),
    FileConflictError: (409, "conflict"),
    ProviderError: (502, "provider_error"),
    StorageNotConfiguredError: (503, "provider_not_configured"),
}


def error_response(
    request: Request,
    status: int,
    code: str,
    message: str,
    provider: bool,
) -> JSONResponse:
    """
        Build the error body and log one line about the failed request.

        The log has the operation, error code, HTTP status, whether the
        storage provider was involved, and the request id. It does not log
        the error message, query values, request body or any credentials.
    """
    route = request.scope.get("route")
    operation = getattr(route, "name", None) or request.url.path
    request_id = getattr(request.state, "request_id", None)

    # 5xx means the request could not be completed on our side or the
    # provider's. 4xx is a problem with the request itself.
    level = logging.ERROR if status >= 500 else logging.WARNING
    request_logger.log(
        level,
        "request_failed operation=%s error=%s status=%s provider=%s request_id=%s",
        operation,
        code,
        status,
        "yes" if provider else "no",
        request_id,
        extra={
            "operation": operation,
            "error_code": code,
            "status": status,
            "provider": provider,
            "request_id": request_id,
        },
    )

    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
            }
        },
    )


def provider_involved(exc: StorageError) -> bool:
    # Provider code raises our errors `from` the provider exception (see
    # AGENTS.md), so a cause means the provider was called and failed.
    # Errors from our own checks, like a bad path, have no cause.
    if isinstance(exc, (ProviderError, StorageNotConfiguredError)):
        return True
    return exc.__cause__ is not None


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
    )

    app.include_router(api_router)

    # Give every request an id so a failure in the logs can be matched to
    # the response the caller got. A caller can send its own X-Request-ID.
    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    @app.exception_handler(StorageError)
    async def handle_storage_error(
        request: Request,
        exc: StorageError,
    ):
        status, code = ERRORS.get(type(exc), (502, "provider_error"))

        return error_response(
            request,
            status,
            code,
            str(exc),
            provider_involved(exc),
        )

    # FastAPI rejects badly typed input (e.g. a number where a string is
    # expected) with its own 422 body. Return our 400 error shape instead.
    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ):
        first = exc.errors()[0]

        # A body that isn't JSON at all has no field name, only a character
        # position, which made the message read "1: JSON decode error".
        if first["type"] == "json_invalid":
            message = "request body is not valid JSON"
        else:
            field = ".".join(str(part) for part in first["loc"][1:]) or "request"
            message = f"{field}: {first['msg']}"

        return error_response(
            request,
            400,
            "invalid_request",
            message,
            provider=False,
        )

    # FastAPI answers an unknown URL (404) or a wrong method (405) itself,
    # with {"detail": "..."}. Return our error shape instead, so a caller
    # never has to handle two formats.
    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request,
        exc: StarletteHTTPException,
    ):
        route = f"{request.method} {request.url.path}"

        if exc.status_code == 404:
            code, message = "not_found", f"No such endpoint: {route}"
        elif exc.status_code == 405:
            code, message = "method_not_allowed", f"Method not allowed: {route}"
        else:
            code, message = "http_error", str(exc.detail)

        response = error_response(request, exc.status_code, code, message, provider=False)
        # Keeps the Allow header FastAPI sets on a 405
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    # Anything not handled above is a bug. Return a fixed message so the
    # caller never sees the exception text, and keep the detail in the log.
    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request,
        exc: Exception,
    ):
        # Method, path and exception type only. No query string, headers,
        # body or exception message, which may hold paths or secrets.
        logger.error(
            "internal_error method=%s path=%s status=500 error=%s request_id=%s",
            request.method,
            request.url.path,
            type(exc).__name__,
            getattr(request.state, "request_id", None),
        )

        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "Internal server error",
                }
            },
        )

    # Idempotency-Key problems. Each error carries its own status and code,
    # and a fixed message that never shows Redis details or the caller's key.
    # They are not StorageErrors, so they are not in ERRORS. Registered for
    # the base class, this handler is chosen before the catch-all above, so
    # they never become a 500. provider=False: the provider was not asked
    # (or not asked again), even when the error was raised from a Redis one.
    @app.exception_handler(IdempotencyError)
    async def handle_idempotency_error(
        request: Request,
        exc: IdempotencyError,
    ):
        return error_response(
            request,
            exc.status_code,
            exc.code,
            exc.message,
            provider=False,
        )

    return app


app = create_app()
