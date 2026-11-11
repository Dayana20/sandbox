import dropbox
from dropbox.exceptions import ApiError, DropboxException
from dropbox.files import DeletedMetadata, FileMetadata, FolderMetadata, WriteMode

from app.errors import (
    FileNotFoundError,
    InvalidRequestError,
    ProviderError,
    ProviderUnavailableError,
)
from app.models.file import FileResource, format_utc_timestamp
from app.providers.dropbox.error_mapping import (
    logs_dropbox_errors,
    translate_dropbox_exception,
    translate_folder_lookup_error,
    translate_lookup_error,
    translate_write_error,
)

from requests.exceptions import RequestException

class DropboxStorage:

    def __init__(self, client: dropbox.Dropbox):
        self.client = client

    @logs_dropbox_errors
    def upload(
        self,
        path: str,
        content: bytes,
    ) -> FileResource:
        """
            Upload a new file to cloud storage.

            Args:
                path (str): Where to save the file, e.g. "/docs/report.pdf".
                content (bytes): The file contents.
            Returns:
                FileResource: Metadata of the uploaded file.
            Raises:
                FileConflictError: If a file already exists at this path.
        """
        # WriteMode.add + autorename=False so we never overwrite or rename
        # an existing file. Dropbox returns a conflict error instead.
        try:
            metadata = self.client.files_upload(
                content,
                path,
                mode=WriteMode.add,
                autorename=False,
                mute=True,
                strict_conflict=True,
            )
        except RequestException as exc:
            raise ProviderError(f"Dropbox could not upload: {path}") from exc
        except ApiError as exc:
            if exc.error.is_path():
                raise translate_write_error(exc.error.get_path().reason, path) from exc
            raise ProviderError(f"Dropbox could not upload: {path}") from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc

        return self.to_file_resource(metadata)

    @logs_dropbox_errors
    def get_metadata(
        self,
        path: str,
    ) -> FileResource:
        """
            Fetch metadata of a file from cloud storage.

            Args:
                path (str): The file to look up, e.g. "/docs/report.pdf".
            Returns:
                FileResource: Metadata of the file.
            Raises:
                FileNotFoundError: If nothing exists at this path.
                InvalidRequestError: If the path is a folder or not a valid Dropbox path.
                PermissionDeniedError: If the token can't read this path.
                ProviderError: If Dropbox fails.
        """
        try:
            metadata = self.client.files_get_metadata(path)
        except RequestException as exc:
            raise ProviderUnavailableError(
                f"Dropbox could not read metadata: {path}"
            ) from exc
        except ApiError as exc:
            if exc.error.is_path():
                raise translate_lookup_error(exc.error.get_path(), path) from exc
            raise ProviderError(f"Dropbox could not read metadata: {path}") from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc

        if isinstance(metadata, DeletedMetadata):
            raise FileNotFoundError(f"File not found: {path}")

        if not isinstance(metadata, (FileMetadata, FolderMetadata)):
            raise ProviderError("Dropbox returned unsupported metadata")

        return self.to_file_resource(metadata)

    @logs_dropbox_errors
    def list_files(
        self,
        path: str,
    ) -> list[FileResource]:
        """Return every direct child of a Dropbox folder across all pages."""
        dropbox_path = "" if path == "/" else path

        try:
            result = self.client.files_list_folder(
                dropbox_path,
                recursive=False,
            )
            entries = list(result.entries)
            seen_cursors: set[str] = set()

            while result.has_more:
                cursor = result.cursor
                if not cursor or cursor in seen_cursors:
                    raise ProviderError("Dropbox returned an invalid list cursor")
                seen_cursors.add(cursor)
                result = self.client.files_list_folder_continue(cursor)
                entries.extend(result.entries)
        except RequestException as exc:
            raise ProviderUnavailableError(
                "Dropbox could not list the requested folder"
            ) from exc
        except ApiError as exc:
            if exc.error.is_path():
                raise translate_folder_lookup_error(
                    exc.error.get_path(), path
                ) from exc
            raise ProviderError("Dropbox could not list the requested folder") from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc

        resources: list[FileResource] = []
        for entry in entries:
            if isinstance(entry, FileMetadata):
                resources.append(self.to_file_resource(entry, resource_type="file"))
            elif isinstance(entry, FolderMetadata):
                resources.append(self.to_file_resource(entry, resource_type="folder"))
            else:
                raise ProviderError("Dropbox returned unsupported list metadata")

        return sorted(resources, key=lambda resource: resource.path)

    @logs_dropbox_errors
    def download(
        self,
        path: str,
    ) -> bytes:
        """
            Download the content of a file from cloud storage.
    
            Args:
                file_path (str): The path to the file in cloud
                storage.
            Returns:
                Response: The content of the file.
            Raises:
                FileNotFoundError: If the file does not exist in cloud storage.
        """
        try:
            metadata, response = self.client.files_download(path)
        except RequestException as exc:
            raise ProviderError(f"Dropbox could not download: {path}") from exc
        except ApiError as exc:
            if exc.error.is_path():
                raise translate_lookup_error(exc.error.get_path(), path) from exc
            raise ProviderError(f"Dropbox could not download: {path}") from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc
        # return the content of the file as response.content, which is a bytes object
        return response.content

    @logs_dropbox_errors
    def move(
        self,
        path: str,
        new_path: str,
    ) -> FileResource:
        """
            Rename or move a file in cloud storage.

            Args:
                path (str): The file to move, e.g. "/docs/report.pdf".
                new_path (str): Where it should end up, e.g. "/archive/report.pdf".
            Returns:
                FileResource: Metadata of the file at its new path. The id does not change.
            Raises:
                FileNotFoundError: If nothing exists at path.
                InvalidRequestError: If path is a folder.
                FileConflictError: If something already exists at new_path.
                PermissionDeniedError: If the token can't move this file.
        """
        # Dropbox moves folders with everything inside, so check it is a file first
        try:
            metadata = self.client.files_get_metadata(path)
        except RequestException as exc:
            raise ProviderError(f"Dropbox could not inspect: {path}") from exc
        except ApiError as exc:
            if exc.error.is_path():
                raise translate_lookup_error(exc.error.get_path(), path) from exc
            raise ProviderError(f"Dropbox could not inspect: {path}") from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc

        if not isinstance(metadata, FileMetadata):
            raise InvalidRequestError(f"Only files can be moved: {path}")

        # autorename=False so an existing file at new_path is never overwritten
        # or renamed. Dropbox returns a conflict error instead.
        try:
            result = self.client.files_move_v2(path, new_path, autorename=False)
        except RequestException as exc:
            raise ProviderError(f"Dropbox could not move: {path}") from exc
        except ApiError as exc:
            error = exc.error
            if error.is_from_lookup():
                raise translate_lookup_error(error.get_from_lookup(), path) from exc
            if error.is_from_write():
                raise translate_write_error(error.get_from_write(), path) from exc
            if error.is_to():
                raise translate_write_error(error.get_to(), new_path) from exc
            raise ProviderError(f"Dropbox could not move: {path}") from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc

        return self.to_file_resource(result.metadata)

    @logs_dropbox_errors
    def delete(
        self,
        path: str,
    ) -> None:
        """
            Delete a file from cloud storage.

            Args:
                path (str): The file to delete, e.g. "/docs/report.pdf".
            Raises:
                FileNotFoundError: If nothing exists at this path.
                InvalidRequestError: If the path is a folder.
                PermissionDeniedError: If the token can't delete this path.
        """
        # Dropbox deletes folders recursively, so check it is a file first
        try:
            metadata = self.client.files_get_metadata(path)
        except RequestException as exc:
            raise ProviderError(f"Dropbox could not inspect: {path}") from exc
        except ApiError as exc:
            raise translate_lookup_error(exc.error.get_path(), path) from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc

        if not isinstance(metadata, FileMetadata):
            raise InvalidRequestError(f"Only files can be deleted: {path}")

        try:
            self.client.files_delete_v2(path)
        except RequestException as exc:
            raise ProviderError(f"Dropbox could not delete: {path}") from exc
        except ApiError as exc:
            if exc.error.is_path_lookup():
                raise translate_lookup_error(exc.error.get_path_lookup(), path) from exc
            if exc.error.is_path_write():
                raise translate_write_error(exc.error.get_path_write(), path) from exc
            raise ProviderError(f"Dropbox could not delete: {path}") from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc

    def to_file_resource(
        self,
        metadata: FileMetadata | FolderMetadata,
        *,
        resource_type: str | None = None,
    ) -> FileResource:
        if isinstance(metadata, FileMetadata):
            return FileResource(
                id=metadata.id,
                name=metadata.name,
                path=metadata.path_display,
                size=metadata.size,
                modified_at=format_utc_timestamp(metadata.server_modified),
                etag=metadata.rev,
                type=resource_type,
            )

        return FileResource(
            id=metadata.id,
            name=metadata.name,
            path=metadata.path_display,
            size=None,
            modified_at=None,
            etag=None,
            type=resource_type,
        )
    @logs_dropbox_errors
    def check_health(
        self,
    ) -> None:
        """
            Raise an exception if the provider is unreachable or misconfigured.

            Args:
                None
            Returns:
                None
        """
        try:
            self.client.users_get_current_account()
        except Exception as exc:
            raise ProviderUnavailableError(
                "Dropbox could not be reached"
            ) from exc
