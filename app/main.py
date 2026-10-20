from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.core.config import settings
from app.errors import (
    FileConflictError,
    FileNotFoundError,
    InvalidRequestError,
    PermissionDeniedError,
    ProviderError,
    StorageNotConfiguredError
)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
    )

    app.include_router(api_router)

    @app.exception_handler(FileNotFoundError)
    async def handle_not_found(
        request: Request,
        exc: FileNotFoundError,
    ):
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "not_found",
                    "message": str(exc),
                }
            },
        )

    @app.exception_handler(PermissionDeniedError)
    async def handle_permission_denied(
        request: Request,
        exc: PermissionDeniedError,
    ):
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "code": "permission_denied",
                    "message": str(exc),
                }
            },
        )

    @app.exception_handler(FileConflictError)
    async def handle_conflict(
        request: Request,
        exc: FileConflictError,
    ):
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "conflict",
                    "message": str(exc),
                }
            },
        )

    @app.exception_handler(ProviderError)
    async def handle_provider_error(
        request: Request,
        exc: ProviderError,
    ):
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "code": "provider_error",
                    "message": str(exc),
                }
            },
        )

    @app.exception_handler(InvalidRequestError)
    async def handle_invalid_request(
        request: Request,
        exc: InvalidRequestError,
    ):
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": str(exc),
                }
            },
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

        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": message,
                }
            },
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

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": code,
                    "message": message,
                }
            },
            # Keeps the Allow header FastAPI sets on a 405
            headers=exc.headers,
        )

    @app.exception_handler(StorageNotConfiguredError)
    async def handle_storage_configured_error(
        request: Request,
        exc: StorageNotConfiguredError,
    ):
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "provider_not_configured",
                    "message": str(exc),
                }
            },
        )  

    return app


app = create_app()