"""Errors Codes."""

from typing import ClassVar


class StorageError(Exception):
    """Storage Error Codes."""

    status_code: ClassVar[int] = 500
    code: ClassVar[str] = "internal_error"

    def __init__(self, message: str = "") -> None:
        """Descriptive error message."""
        super().__init__(message)
        self.message = message


class InvalidRequestError(StorageError):
    """Missing field, malformed path, invalid JSON or multipart."""

    status_code = 400
    code = "invalid_request"


class PermissionDeniedError(StorageError):
    """The provider refused the service's credentials or permissions."""

    status_code = 403
    code = "permission_denied"


class NotFoundError(StorageError):
    """Nothing exists at the path."""

    status_code = 404
    code = "not_found"


class ConflictError(StorageError):
    """The destination is occupied, or a revision check refused a stale write."""

    status_code = 409
    code = "conflict"


class FileTooLargeError(StorageError):
    """The upload is above the accepted size."""

    status_code = 413
    code = "file_too_large"


class InvalidOperationError(StorageError):
    """Valid input for an operation the contract forbids."""

    status_code = 422
    code = "invalid_operation"


class ProviderError(StorageError):
    """Any other provider failure, or a known partial move or folder delete."""

    status_code = 502
    code = "provider_error"


class ProviderUnavailableError(StorageError):
    """The provider is unreachable or timed out."""

    status_code = 503
    code = "provider_unavailable"
