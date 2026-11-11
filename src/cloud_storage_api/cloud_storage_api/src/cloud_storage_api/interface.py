"""Provider interface that every storage adapter implements."""

from abc import ABC, abstractmethod

from .models import FileInfo


class DocumentStorage(ABC):
    """Operations of the shared Document Storage contract."""

    @abstractmethod
    def create(self, path: str, content: bytes) -> FileInfo:
        """Create a file. Raise ConflictError if one already exists."""

    @abstractmethod
    def replace(self, path: str, content: bytes) -> FileInfo:
        """Replace a file. Raise NotFoundError if missing; never create."""

    @abstractmethod
    def download(self, path: str) -> bytes:
        """Return the exact bytes of a file."""

    @abstractmethod
    def get_metadata(self, path: str) -> FileInfo:
        """Return file info. Raise NotFoundError if missing."""

    @abstractmethod
    def list_files(self, path: str) -> list[FileInfo]:
        """Return the direct children of a folder, sorted by path, every page fetched."""

    @abstractmethod
    def move(self, from_path: str, to_path: str) -> FileInfo:
        """Move a file. Raise ConflictError if the destination exists."""

    @abstractmethod
    def delete(self, path: str) -> None:
        """Delete a file, or a folder with everything in it."""

    @abstractmethod
    def check_health(self) -> None:
        """Make one lightweight provider call. Raise ProviderUnavailableError on failure."""
