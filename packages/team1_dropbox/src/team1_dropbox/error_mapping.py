"""Translate Dropbox SDK failures into the shared storage error hierarchy."""

from typing import Literal

from cloud_storage_api.errors import (
    ConflictError,
    InvalidOperationError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    ProviderError,
    ProviderUnavailableError,
    StorageError,
)
from dropbox.exceptions import (
    AuthError,
    BadInputError,
    DropboxException,
    HttpError,
    InternalServerError,
    PathRootError,
    RateLimitError,
)
from dropbox.files import LookupError, WriteError
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    RequestException,
    Timeout,
)

ExpectedKind = Literal["file", "folder", "either"]


def translate_dropbox_exception(exc: DropboxException) -> StorageError:
    """Map SDK-wide errors without exposing provider free text."""
    if isinstance(exc, AuthError):
        return PermissionDeniedError("Dropbox authentication or authorization failed.")
    if isinstance(exc, BadInputError):
        return InvalidRequestError("Dropbox rejected the request.")
    if isinstance(exc, PathRootError):
        return InvalidRequestError("Dropbox rejected the configured path root.")
    if isinstance(exc, InternalServerError):
        return ProviderUnavailableError("Dropbox is temporarily unavailable.")
    if isinstance(exc, HttpError) and exc.status_code >= 500:
        return ProviderUnavailableError("Dropbox is temporarily unavailable.")
    if isinstance(exc, RateLimitError):
        return ProviderError("Dropbox rate limited the request.")
    return ProviderError("Dropbox request failed.")


def translate_request_exception(exc: RequestException) -> StorageError:
    """Distinguish connectivity failures from other HTTP client failures."""
    if isinstance(exc, (Timeout, RequestsConnectionError)):
        return ProviderUnavailableError("Dropbox could not be reached.")
    return ProviderError("Dropbox request failed.")


def translate_lookup_error(
    error: LookupError,
    *,
    expected: ExpectedKind = "either",
) -> StorageError:
    """Translate a Dropbox lookup union for the operation's expected kind."""
    if error.is_not_found():
        return NotFoundError("Nothing exists at the requested path.")
    if error.is_malformed_path():
        return InvalidRequestError("Dropbox rejected the path.")
    if error.is_restricted_content():
        return PermissionDeniedError("Dropbox denied access to the requested path.")
    if error.is_not_file() and expected == "file":
        return InvalidOperationError("The operation requires a file path.")
    if (error.is_not_folder() or error.is_not_file()) and expected == "folder":
        return InvalidOperationError("The operation requires a folder path.")
    return ProviderError("Dropbox could not look up the requested path.")


def translate_write_error(error: WriteError) -> StorageError:
    """Translate a Dropbox write union without including a caller path."""
    if error.is_malformed_path() or error.is_disallowed_name():
        return InvalidRequestError("Dropbox rejected the destination path.")
    if error.is_conflict():
        return ConflictError("A resource already exists at the destination path.")
    if error.is_no_write_permission():
        return PermissionDeniedError("Dropbox denied write access.")
    return ProviderError("Dropbox could not complete the write.")
