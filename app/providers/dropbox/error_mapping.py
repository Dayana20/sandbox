import functools
import logging
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from dropbox.exceptions import (
    ApiError,
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
    StorageError,
)


logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def logs_dropbox_errors(method: Callable[P, R]) -> Callable[P, R]:
    """
        Log every Dropbox failure a DropboxStorage method turns into one of our errors.

        The translators replace Dropbox's error with a short message for the
        caller, so this keeps the original detail in the server log. Only
        errors raised `from` a Dropbox exception are logged. Checks we make
        ourselves, like refusing a folder, are not Dropbox failures.

        Logs one line per failure with the operation, the path, our error
        type, the Dropbox error and Dropbox's request id. It never logs the
        token, file contents, or Dropbox's free-text messages.
    """

    @functools.wraps(method)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return method(*args, **kwargs)
        except StorageError as exc:
            cause = exc.__cause__
            if isinstance(cause, DropboxException):
                # args[0] is the DropboxStorage instance, args[1] the path
                path = args[1] if len(args) > 1 else kwargs.get("path")
                _log_dropbox_error(method.__name__, path, exc, cause)
            raise

    return wrapper


def _log_dropbox_error(
    operation: str,
    path: object,
    error: StorageError,
    cause: DropboxException,
) -> None:
    # ApiError and AuthError carry a typed Dropbox error union, e.g.
    # GetMetadataError('path', LookupError('not_found', None)). Other
    # exceptions only carry free text, which may echo the request, so only
    # their class name is logged.
    if isinstance(cause, (ApiError, AuthError)):
        dropbox_error = f"{type(cause).__name__}: {cause.error!r}"
    else:
        dropbox_error = type(cause).__name__

    # A ProviderError means Dropbox itself failed. The rest are the caller's
    # problem (bad path, missing file, conflict, permission).
    level = logging.ERROR if isinstance(error, ProviderError) else logging.WARNING

    logger.log(
        level,
        "dropbox_error operation=%s path=%s error=%s dropbox_error=%s request_id=%s",
        operation,
        path,
        type(error).__name__,
        dropbox_error,
        cause.request_id,
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

    if error.is_not_file():
        return InvalidRequestError(
            f"Path is not a file: {path}"
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

    if error.is_disallowed_name():
        return InvalidRequestError(
            f"Dropbox does not allow this filename: {path}"
        )

    return ProviderError(
        f"Dropbox could not write to: {path}"
    )