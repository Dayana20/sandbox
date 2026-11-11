"""Shared Document Storage contract."""

from .errors import (
    ConflictError,
    FileTooLargeError,
    InvalidOperationError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    ProviderError,
    ProviderUnavailableError,
    StorageError,
)
from .interface import DocumentStorage
from .models import FileInfo

__all__ = [
    "ConflictError",
    "DocumentStorage",
    "FileInfo",
    "FileTooLargeError",
    "InvalidOperationError",
    "InvalidRequestError",
    "NotFoundError",
    "PermissionDeniedError",
    "ProviderError",
    "ProviderUnavailableError",
    "StorageError",
]
