"""Public shared-contract adapter for Team 1's Dropbox implementation."""

from collections.abc import Mapping

import dropbox
from cloud_storage_api import DocumentStorage, FileInfo
from cloud_storage_api.errors import InvalidRequestError

from .backend import DropboxBackend
from .client import create_dropbox_client, create_dropbox_client_from_env


class Team1DropboxStorage(DocumentStorage):
    """A standalone Dropbox implementation of ``DocumentStorage``.

    Supply either an authenticated Dropbox SDK client or all three refresh-token
    credential values. Use :meth:`from_env` when environment-based construction
    is preferable.
    """

    def __init__(
        self,
        client: dropbox.Dropbox | None = None,
        *,
        app_key: str | None = None,
        app_secret: str | None = None,
        refresh_token: str | None = None,
    ) -> None:
        supplied_credentials = (app_key, app_secret, refresh_token)
        if client is not None and any(value is not None for value in supplied_credentials):
            raise InvalidRequestError(
                "Supply either a Dropbox client or refresh-token credentials, not both."
            )
        if client is None:
            client = create_dropbox_client(
                app_key=app_key or "",
                app_secret=app_secret or "",
                refresh_token=refresh_token or "",
            )
        self._backend = DropboxBackend(client)

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "Team1DropboxStorage":
        """Build from ``DROPBOX_APP_KEY``, ``DROPBOX_APP_SECRET`` and
        ``DROPBOX_REFRESH_TOKEN`` without loading a particular ``.env`` file.
        """
        return cls(client=create_dropbox_client_from_env(environ))

    def create(self, path: str, content: bytes) -> FileInfo:
        return self._backend.create(_validate_path(path), _validate_content(content))

    def replace(self, path: str, content: bytes) -> FileInfo:
        return self._backend.replace(_validate_path(path), _validate_content(content))

    def download(self, path: str) -> bytes:
        return self._backend.download(_validate_path(path))

    def get_metadata(self, path: str) -> FileInfo:
        return self._backend.get_metadata(_validate_path(path))

    def list_files(self, path: str) -> list[FileInfo]:
        return self._backend.list_files(_validate_path(path, allow_root=True))

    def move(self, from_path: str, to_path: str) -> FileInfo:
        return self._backend.move(_validate_path(from_path), _validate_path(to_path))

    def delete(self, path: str) -> None:
        self._backend.delete(_validate_path(path))

    def check_health(self) -> None:
        self._backend.check_health()


def _validate_path(path: str, *, allow_root: bool = False) -> str:
    if not isinstance(path, str) or not path:
        raise InvalidRequestError("path is required")
    if any(ord(char) < 32 or ord(char) == 127 for char in path):
        raise InvalidRequestError("path must not contain control characters")

    canonical = path if path.startswith("/") else f"/{path}"
    if canonical == "/":
        if allow_root:
            return canonical
        raise InvalidRequestError("path must identify a resource below root")
    if canonical.endswith("/"):
        raise InvalidRequestError("path must identify a resource below root")
    if any(part in ("", ".", "..") for part in canonical[1:].split("/")):
        raise InvalidRequestError("path contains an invalid segment")
    return canonical


def _validate_content(content: bytes) -> bytes:
    if not isinstance(content, bytes):
        raise InvalidRequestError("content must be bytes")
    return content
