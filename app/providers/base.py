from typing import Protocol

from app.models.file import FileResource
from cloud_storage_api import FileInfo


class DocumentStorage(Protocol):
    """
        What the service needs from a document store.

        Routes only use this interface. They never see which provider is
        behind it. Paths are absolute inside the storage root, e.g.
        "/docs/report.pdf". Implementations return our own types
        (FileResource, bytes), never provider SDK objects.
    """

    def upload(
        self,
        path: str,
        content: bytes,
    ) -> FileResource:
        """
            Save a new file at path. Changes state.

            Never overwrites or renames an existing file.
            Returns the stored file's metadata.
        """
        ...

    def replace(
        self,
        path: str,
        content: bytes,
    ) -> FileResource:
        """
            Replace the contents of the existing file at path. Changes state.

            Never creates a file: a missing path is FileNotFoundError.
            If the file changes while it is being replaced, nothing is
            written and FileConflictError is raised.
            Returns the file's new metadata. The id does not change.
        """
        ...

    def get_metadata(
        self,
        path: str,
    ) -> FileResource:
        """
            Return provider-neutral metadata of the file or folder at path.
            Read only.
        """
        ...

    def list_files(
        self,
        path: str,
    ) -> list[FileResource]:
        """Return every direct child of a folder, sorted by canonical path."""
        ...

    def download(
        self,
        path: str,
    ) -> bytes:
        """
            Return the exact bytes of the file at path. Read only.
        """
        ...

    def move(
        self,
        from_path: str,
        to_path: str,
    ) -> FileInfo:
        """
            Rename or move the file at from_path to to_path. Changes state.

            The file keeps its id. Never overwrites a file at to_path.
            Returns the file's metadata at its new path.
        """
        ...

    def delete(
        self,
        path: str,
    ) -> None:
        """
            Delete the file at path, or the folder at path with everything
            in it. Changes state.
        """
        ...

    def check_health(
        self,
    ) -> None:
        """
            Raise an exception if the provider is unreachable or misconfigured.

            This is a quick check to see if the provider is available.
        """
        ...
