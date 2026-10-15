import dropbox
from dropbox.exceptions import ApiError, DropboxException
from dropbox.files import FileMetadata, WriteMode

from app.errors import InvalidRequestError, ProviderError
from app.models.file import FileResource
from app.providers.dropbox.error_mapping import (
    translate_dropbox_exception,
    translate_lookup_error,
    translate_write_error,
)


class DropboxStorage:

    def __init__(self, client: dropbox.Dropbox):
        self.client = client

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
        except ApiError as exc:
            if exc.error.is_path():
                raise translate_write_error(exc.error.get_path().reason, path) from exc
            raise ProviderError(f"Dropbox could not upload: {path}") from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc

        return self.to_file_resource(metadata)

    def get_metadata(
        self,
        path: str,
    ) -> FileResource:
        """
            Fetch metadata of a file from cloud storage.

            Args:
                file_path (str): The path to the file in cloud
                storage.
            Returns:
                dict: The metadata of the file.
            Raises:
                FileNotFoundError: If the file does not exist in cloud storage.
        """
        # check if the file exists
        try:
            metadata = self.client.files_get_metadata(path)
            return self.to_file_resource(metadata)
        except dropbox.exceptions.ApiError as e:
            if isinstance(e.error, dropbox.files.GetMetadataError):
                raise FileNotFoundError(f"File not found: {path}")
            else:
                raise e
        # raise NotImplementedError

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
                str: The content of the file.
            Raises:
                FileNotFoundError: If the file does not exist in cloud storage.
        """
        raise NotImplementedError

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
        except ApiError as exc:
            raise translate_lookup_error(exc.error.get_path(), path) from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc

        if not isinstance(metadata, FileMetadata):
            raise InvalidRequestError(f"Only files can be deleted: {path}")

        try:
            self.client.files_delete_v2(path)
        except ApiError as exc:
            if exc.error.is_path_lookup():
                raise translate_lookup_error(exc.error.get_path_lookup(), path) from exc
            if exc.error.is_path_write():
                raise translate_write_error(exc.error.get_path_write(), path) from exc
            raise ProviderError(f"Dropbox could not delete: {path}") from exc
        except DropboxException as exc:
            raise translate_dropbox_exception(exc) from exc

    def to_file_resource(self, metadata: dropbox.files.FileMetadata) -> FileResource:
        return FileResource(
            id=metadata.id,
            name=metadata.name,
            path=metadata.path_display,
            size=metadata.size,
            modified_at=metadata.server_modified,
        )