from typing import Protocol

from app.models.file import FileResource


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

    def get_metadata(
        self,
        path: str,
    ) -> FileResource:
        """
            Return metadata of the file at path. Read only.
        """
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
        path: str,
        new_path: str,
    ) -> FileResource:
        """
            Rename or move the file at path to new_path. Changes state.

            The file keeps its id. Never overwrites a file at new_path.
            Returns the file's metadata at its new path.
        """
        ...

    def delete(
        self,
        path: str,
    ) -> None:
        """
            Delete the file at path. Changes state.

            Only files are deleted, never folders.
        """
        ...
