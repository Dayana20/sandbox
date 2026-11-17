"""Dropbox-specific implementation used by the public contract adapter."""

from datetime import datetime, timezone
from typing import NoReturn

import dropbox
from cloud_storage_api import FileInfo
from cloud_storage_api.errors import (
    ConflictError,
    InvalidOperationError,
    NotFoundError,
    ProviderError,
    ProviderUnavailableError,
)
from dropbox.exceptions import ApiError, DropboxException
from dropbox.files import (
    DeletedMetadata,
    FileMetadata,
    FolderMetadata,
    WriteMode,
)
from requests.exceptions import RequestException

from .error_mapping import (
    translate_dropbox_exception,
    translate_lookup_error,
    translate_request_exception,
    translate_write_error,
)


class DropboxBackend:
    """Execute Dropbox SDK calls and return shared contract values."""

    def __init__(self, client: dropbox.Dropbox) -> None:
        self._client = client

    def create(self, path: str, content: bytes) -> FileInfo:
        try:
            metadata = self._client.files_upload(
                content,
                path,
                mode=WriteMode.add,
                autorename=False,
                mute=True,
                strict_conflict=True,
            )
        except RequestException as exc:
            raise translate_request_exception(exc) from exc
        except ApiError as exc:
            if exc.error.is_path():
                raise translate_write_error(exc.error.get_path().reason) from exc
            raise ProviderError("Dropbox could not create the file.") from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc
        except Exception as exc:
            self._raise_unexpected(exc)

        return _file_info(metadata)

    def replace(self, path: str, content: bytes) -> FileInfo:
        try:
            current = self._client.files_get_metadata(path)
        except RequestException as exc:
            raise translate_request_exception(exc) from exc
        except ApiError as exc:
            if exc.error.is_path():
                raise translate_lookup_error(exc.error.get_path(), expected="file") from exc
            raise ProviderError("Dropbox could not inspect the file.") from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc
        except Exception as exc:
            self._raise_unexpected(exc)

        if not isinstance(current, FileMetadata):
            raise InvalidOperationError("Only files can be replaced.")

        try:
            metadata = self._client.files_upload(
                content,
                path,
                mode=WriteMode.update(current.rev),
                autorename=False,
                mute=True,
                strict_conflict=True,
            )
        except RequestException as exc:
            raise translate_request_exception(exc) from exc
        except ApiError as exc:
            if exc.error.is_path():
                reason = exc.error.get_path().reason
                if reason.is_conflict():
                    raise ConflictError("The file changed while it was being replaced.") from exc
                raise translate_write_error(reason) from exc
            raise ProviderError("Dropbox could not replace the file.") from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc
        except Exception as exc:
            self._raise_unexpected(exc)

        return _file_info(metadata)

    def download(self, path: str) -> bytes:
        try:
            _, response = self._client.files_download(path)
        except RequestException as exc:
            raise translate_request_exception(exc) from exc
        except ApiError as exc:
            if exc.error.is_path():
                raise translate_lookup_error(exc.error.get_path(), expected="file") from exc
            raise ProviderError("Dropbox could not download the file.") from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc
        except Exception as exc:
            self._raise_unexpected(exc)

        content = response.content
        if not isinstance(content, bytes):
            raise ProviderError("Dropbox returned an invalid download response.")
        return content

    def get_metadata(self, path: str) -> FileInfo:
        try:
            metadata = self._client.files_get_metadata(path)
        except RequestException as exc:
            raise translate_request_exception(exc) from exc
        except ApiError as exc:
            if exc.error.is_path():
                raise translate_lookup_error(exc.error.get_path()) from exc
            raise ProviderError("Dropbox could not read metadata.") from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc
        except Exception as exc:
            self._raise_unexpected(exc)

        if isinstance(metadata, DeletedMetadata):
            raise NotFoundError("Nothing exists at the requested path.")
        return _metadata_to_file_info(metadata)

    def list_files(self, path: str) -> list[FileInfo]:
        dropbox_path = "" if path == "/" else path
        try:
            result = self._client.files_list_folder(dropbox_path, recursive=False)
            entries = list(result.entries)
            seen_cursors: set[str] = set()

            while result.has_more:
                cursor = result.cursor
                if not cursor or cursor in seen_cursors:
                    raise ProviderError("Dropbox returned an invalid list cursor.")
                seen_cursors.add(cursor)
                result = self._client.files_list_folder_continue(cursor)
                entries.extend(result.entries)
        except RequestException as exc:
            raise translate_request_exception(exc) from exc
        except ApiError as exc:
            if exc.error.is_path():
                raise translate_lookup_error(exc.error.get_path(), expected="folder") from exc
            raise ProviderError("Dropbox could not list the folder.") from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc
        except (ProviderError, NotFoundError, InvalidOperationError):
            raise
        except Exception as exc:
            self._raise_unexpected(exc)

        resources = [_metadata_to_file_info(entry, list_entry=True) for entry in entries]
        return sorted(resources, key=lambda resource: resource.path)

    def move(self, from_path: str, to_path: str) -> FileInfo:
        try:
            current = self._client.files_get_metadata(from_path)
        except RequestException as exc:
            raise translate_request_exception(exc) from exc
        except ApiError as exc:
            if exc.error.is_path():
                raise translate_lookup_error(exc.error.get_path(), expected="file") from exc
            raise ProviderError("Dropbox could not inspect the source.") from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc
        except Exception as exc:
            self._raise_unexpected(exc)

        if not isinstance(current, FileMetadata):
            raise InvalidOperationError("Only files can be moved.")

        try:
            result = self._client.files_move_v2(from_path, to_path, autorename=False)
        except RequestException as exc:
            raise translate_request_exception(exc) from exc
        except ApiError as exc:
            error = exc.error
            if error.is_from_lookup():
                raise translate_lookup_error(error.get_from_lookup(), expected="file") from exc
            if error.is_from_write():
                raise translate_write_error(error.get_from_write()) from exc
            if error.is_to():
                raise translate_write_error(error.get_to()) from exc
            raise ProviderError("Dropbox could not move the file.") from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc
        except Exception as exc:
            self._raise_unexpected(exc)

        return _file_info(result.metadata)

    def delete(self, path: str) -> None:
        try:
            self._client.files_delete_v2(path)
        except RequestException as exc:
            raise translate_request_exception(exc) from exc
        except ApiError as exc:
            if exc.error.is_path_lookup():
                raise translate_lookup_error(exc.error.get_path_lookup()) from exc
            if exc.error.is_path_write():
                raise translate_write_error(exc.error.get_path_write()) from exc
            raise ProviderError("Dropbox could not delete the resource.") from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc
        except Exception as exc:
            self._raise_unexpected(exc)

    def check_health(self) -> None:
        try:
            self._client.users_get_current_account()
        except Exception as exc:
            raise ProviderUnavailableError("Dropbox health check failed.") from exc

    @staticmethod
    def _raise_unexpected(exc: Exception) -> NoReturn:
        raise ProviderError("Unexpected Dropbox client failure.") from exc


def _metadata_to_file_info(
    metadata: object,
    *,
    list_entry: bool = False,
) -> FileInfo:
    if isinstance(metadata, FileMetadata):
        return _file_info(metadata, list_entry=list_entry)
    if isinstance(metadata, FolderMetadata):
        path = _metadata_path(metadata)
        return FileInfo(
            id=metadata.id,
            name=metadata.name,
            path=path,
            size=None,
            modified_at=None,
            etag=None,
            type="folder" if list_entry else None,
        )
    raise ProviderError("Dropbox returned unsupported metadata.")


def _file_info(metadata: object, *, list_entry: bool = False) -> FileInfo:
    if not isinstance(metadata, FileMetadata):
        raise ProviderError("Dropbox returned unsupported file metadata.")
    return FileInfo(
        id=metadata.id,
        name=metadata.name,
        path=_metadata_path(metadata),
        size=metadata.size,
        modified_at=_format_utc_timestamp(metadata.server_modified),
        etag=metadata.rev,
        type="file" if list_entry else None,
    )


def _metadata_path(metadata: FileMetadata | FolderMetadata) -> str:
    path = metadata.path_display
    if not isinstance(path, str) or not path.startswith("/"):
        raise ProviderError("Dropbox returned metadata without an absolute path.")
    return path


def _format_utc_timestamp(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise ProviderError("Dropbox returned an invalid modification timestamp.")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")
