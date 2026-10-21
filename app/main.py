import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import settings
from app.errors import (
    FileConflictError,
    FileNotFoundError,
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
        field = ".".join(str(part) for part in first["loc"][1:]) or "request"

        return error_response(
            request,
            400,
            "invalid_request",
            f"{field}: {first['msg']}",
            provider=False,
        )

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

    return app


app = create_app()
