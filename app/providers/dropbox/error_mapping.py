from dropbox.exceptions import (
    AuthError,
    BadInputError,
    DropboxException,
    InternalServerError,
    RateLimitError,
)
from dropbox.files import LookupError, WriteError

from app.errors import (
    FileConflictError,
    FileNotFoundError,
    InvalidRequestError,
    PermissionDeniedError,
    ProviderError,
)


def translate_dropbox_exception(
    exc: DropboxException,
) -> Exception:

    if isinstance(exc, AuthError):
        return PermissionDeniedError(
            "Dropbox authentication failed"
        )

    if isinstance(exc, BadInputError):
        return InvalidRequestError(
            "Dropbox rejected the request"
        )

    if isinstance(exc, RateLimitError):
        return ProviderError(
            "Dropbox rate limit exceeded"
        )

    if isinstance(exc, InternalServerError):
        return ProviderError(
            "Dropbox is temporarily unavailable"
        )

    return ProviderError(
        "Dropbox request failed"
    )


def translate_lookup_error(
    error: LookupError,
    path: str,
) -> Exception:

    if error.is_not_found():
        return FileNotFoundError(
            f"File not found: {path}"
        )

    if error.is_malformed_path():
        return InvalidRequestError(
            f"Invalid Dropbox path: {path}"
        )

    if error.is_restricted_content():
        return PermissionDeniedError(
            f"Access denied: {path}"
        )

    return ProviderError(
        f"Unable to access file: {path}"
    )


def translate_write_error(
    error: WriteError,
    path: str,
) -> Exception:

    if error.is_malformed_path():
        return InvalidRequestError(
            f"Invalid Dropbox path: {path}"
        )

    if error.is_conflict():
        return FileConflictError(
            f"File already exists: {path}"
        )

    if error.is_no_write_permission():
        return PermissionDeniedError(
            f"No write permission: {path}"
        )

    if error.is_access_restricted():
        return PermissionDeniedError(
            f"Access restricted: {path}"
        )

    if error.is_disallowed_name():
        return InvalidRequestError(
            f"Dropbox does not allow this filename: {path}"
        )

    return ProviderError(
        f"Dropbox could not write to: {path}"
    )