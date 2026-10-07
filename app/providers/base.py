from typing import Protocol

from app.models.file import FileResource


class DocumentStorage(Protocol):

    def upload(
        self,
        path: str,
        content: bytes,
    ) -> FileResource:
        ...

    def get_metadata(
        self,
        path: str,
    ) -> FileResource:
        ...

    def download(
        self,
        path: str,
    ) -> bytes:
        ...

    def move(
        self,
        path: str,
        new_path: str,
    ) -> FileResource:
        ...

    def delete(
        self,
        path: str,
    ) -> None:
        ...

