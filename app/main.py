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
        field = ".".join(str(part) for part in first["loc"][1:]) or "request"

        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": f"{field}: {first['msg']}",
                }
            },
        )

    return app


app = create_app()
