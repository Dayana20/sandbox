from typing import Any

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


ERROR_DESCRIPTIONS = {
    400: "`invalid_request`: missing or bad input, or a folder where a file is expected",
    403: "`permission_denied`: Dropbox refused access",
    404: "`not_found`: nothing exists at the path",
    409: "`conflict`: a file already exists at the target path",
    502: "`provider_error`: Dropbox failed or is unreachable",
    503: "`provider_not_configured`: Dropbox credentials are missing",
}


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """
        Swagger entries for the errors a route can return, so /docs matches
        the README. The body is always {"error": {"code", "message"}}.
    """
    return {
        status: {"model": ErrorResponse, "description": ERROR_DESCRIPTIONS[status]}
        for status in statuses
    }
