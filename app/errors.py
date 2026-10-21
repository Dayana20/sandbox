class StorageError(Exception):
    """Base exception for document storage errors."""
    #
class StorageNotConfiguredError(StorageError):
    pass


class InvalidRequestError(StorageError):
    pass


class FileNotFoundError(StorageError):
    pass


class PermissionDeniedError(StorageError):
    pass


class FileConflictError(StorageError):
    pass


class ProviderError(StorageError):
    pass


class IdempotencyError(Exception):
    """
        Base for errors about an Idempotency-Key, not about the storage.

        They are not StorageErrors: the provider was not asked, or was not
        asked again. Each carries the HTTP status and error code it is
        returned with. The messages are fixed, so they never include Redis
        details, fingerprints or the caller's key.
    """

    status_code = 409
    code = "idempotency_error"
    message = "Idempotency error"

    def __init__(self) -> None:
        super().__init__(self.message)


class IdempotencyConflictError(IdempotencyError):
    """The key was already used for a different request."""

    code = "idempotency_conflict"
    message = "Idempotency key was already used for a different request"


class IdempotencyInProgressError(IdempotencyError):
    """The same request with this key is still running (or was cut off)."""

    code = "idempotency_in_progress"
    message = (
        "A request with this Idempotency-Key is already in progress. "
        "It was not repeated."
    )


class IdempotencyOutcomeUnknownError(IdempotencyError):
    """The first request may have uploaded the file. It will not be repeated."""

    code = "idempotency_outcome_unknown"
    message = (
        "The original request with this Idempotency-Key may have completed, "
        "so it will not be repeated automatically. Check whether the file "
        "exists before trying again with a new key."
    )


class IdempotencyUnavailableError(IdempotencyError):
    """Idempotency was requested but cannot be enforced, so nothing ran."""

    status_code = 503
    code = "idempotency_unavailable"
    message = "Idempotency service is unavailable"