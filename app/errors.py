class StorageError(Exception):
    """Base exception for document storage errors."""


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