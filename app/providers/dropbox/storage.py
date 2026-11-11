import dropbox
from dropbox.exceptions import ApiError, DropboxException
from dropbox.files import FileMetadata, WriteMode, DeletedMetadata, FolderMetadata
from cloud_storage_api import FileInfo, ConflictError
from datetime import timezone


from app.errors import (
    FileConflictError,
    FileNotFoundError,
    InvalidOperationError,
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
    def replace(
        self,
        path: str,
        content: bytes,
    ) -> FileResource:
        """
            Replace the contents of an existing file in cloud storage.

            Args:
                path (str): The file to replace, e.g. "/docs/report.pdf".
                content (bytes): The new file contents.
            Returns:
                FileResource: Metadata of the replaced file. The id does not change.
            Raises:
                FileNotFoundError: If nothing exists at this path.
                InvalidOperationError: If the path is a folder.
                FileConflictError: If the file changed or was deleted during the replace.
                PermissionDeniedError: If the token can't write this file.
        """
        # Read the current rev first. A missing file stops here, so replace
        # never creates one.
        try:
            current = self.client.files_get_metadata(path)
        except RequestException as exc:
            raise ProviderError(f"Dropbox could not inspect: {path}") from exc
        except ApiError as exc:
            if exc.error.is_path():
                raise translate_lookup_error(exc.error.get_path(), path) from exc
            raise ProviderError(f"Dropbox could not inspect: {path}") from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc

        if not isinstance(current, FileMetadata):
            raise InvalidOperationError(f"Only files can be replaced: {path}")

        # WriteMode.update(rev) only writes if the file is still at that rev.
        # autorename=False makes a mismatch a conflict instead of a
        # "conflicted copy", and strict_conflict=True makes it a conflict even
        # if the file was deleted in between, instead of creating it again.
        try:
            metadata = self.client.files_upload(
                content,
                path,
                mode=WriteMode.update(current.rev),
                autorename=False,
                mute=True,
                strict_conflict=True,
            )
        except RequestException as exc:
            raise ProviderError(f"Dropbox could not replace: {path}") from exc
        except ApiError as exc:
            if exc.error.is_path():
                reason = exc.error.get_path().reason
                if reason.is_conflict():
                    raise FileConflictError(
                        f"File changed while it was being replaced: {path}"
                    ) from exc
                raise translate_write_error(reason, path) from exc
            raise ProviderError(f"Dropbox could not replace: {path}") from exc
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
        from_path: str,
        to_path: str,
    ) -> FileInfo:
        """
            Rename or move a file in cloud storage.

            Args:
                from_path (str): The file to move, e.g. "/docs/report.pdf".
                to_path (str): Where it should end up, e.g. "/archive/report.pdf".
            Returns:
                FileInfo: Metadata of the file at its new path. The id does not change.
            Raises:
                FileNotFoundError: If nothing exists at path.
                InvalidRequestError: If path is a folder.
                FileConflictError: If something already exists at new_path.
                PermissionDeniedError: If the token can't move this file.
        """
        # Dropbox moves folders with everything inside, so check it is a file first
        try:
            metadata = self.client.files_get_metadata(from_path)
        except RequestException as exc:
            raise ProviderError(f"Dropbox could not inspect: {from_path}") from exc
        except ApiError as exc:
            if exc.error.is_path():
                raise translate_lookup_error(exc.error.get_path(), from_path) from exc
            raise ProviderError(f"Dropbox could not inspect: {from_path}") from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc

        if not isinstance(metadata, FileMetadata):
            raise InvalidRequestError(f"Only files can be moved: {from_path}")

        # autorename=False so an existing file at to_path is never overwritten
        # or renamed. Dropbox returns a conflict error instead.
        try:
            result = self.client.files_move_v2(from_path, to_path, autorename=False)
        except RequestException as exc:
            raise ProviderError(f"Dropbox could not move: {from_path}") from exc
        except ApiError as exc:
            error = exc.error
            if error.is_from_lookup():
                raise translate_lookup_error(error.get_from_lookup(), from_path) from exc
            if error.is_from_write():
                raise translate_write_error(error.get_from_write(), from_path) from exc
            if error.is_to():
                destination_error = error.get_to()
                if destination_error.is_conflict():
                    raise ConflictError(f"File already exists: {to_path}") from exc
                raise translate_write_error(destination_error, to_path) from exc
            raise ProviderError(f"Dropbox could not move: {from_path}") from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc

        return self.to_file_info(result.metadata)

    @logs_dropbox_errors
    def delete(
        self,
        path: str,
    ) -> None:
        """
            Delete a file, or a folder with everything in it.

            Args:
                path (str): The file or folder to delete, e.g. "/docs/report.pdf".
            Raises:
                FileNotFoundError: If nothing exists at this path.
                PermissionDeniedError: If the token can't delete this path.
                ProviderError: If Dropbox fails. The outcome is then unknown,
                    so the caller checks the path before retrying.
        """
        # The shared contract deletes folders too, and Dropbox's files_delete_v2
        # already removes a folder with everything in it. So this is one call,
        # whether the path is a file or a folder. The root can't reach here:
        # validate_path rejects "/" for every operation except list.
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

    def to_file_info(self, metadata: dropbox.files.FileMetadata) -> FileInfo:
            modified_at = metadata.server_modified.astimezone(timezone.utc).isoformat()
            modified_at = modified_at.replace("+00:00", "Z")
            return FileInfo(
                id=metadata.id,
                name=metadata.name,
                path=metadata.path_display,
                size=metadata.size,
                modified_at=modified_at,
                etag=metadata.rev,
                type=None,
            )
