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


# Added to the 409 and 503 text of a route that accepts an Idempotency-Key.
IDEMPOTENCY_NOTES = {
    409: "with an `Idempotency-Key` also `idempotency_conflict` (key used for a "
    "different request), `idempotency_in_progress` (still running) or "
    "`idempotency_outcome_unknown` (may have completed, so not repeated)",
    503: "with an `Idempotency-Key` also `idempotency_unavailable` (cannot be "
    "enforced, so nothing was uploaded)",
}


def error_responses(
    *statuses: int, idempotency: bool = False
) -> dict[int | str, dict[str, Any]]:
    """
        Swagger entries for the errors a route can return, so /docs matches
        the README. The body is always {"error": {"code", "message"}}.
    """
    descriptions = dict(ERROR_DESCRIPTIONS)
    if idempotency:
        for status, note in IDEMPOTENCY_NOTES.items():
            descriptions[status] += f"; {note}"

    return {
        status: {"model": ErrorResponse, "description": descriptions[status]}
        for status in statuses
    }
