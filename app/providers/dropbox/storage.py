import dropbox

from app.models.file import FileResource


class DropboxStorage:

    def __init__(self, client: dropbox.Dropbox):
        self.client = client

    def upload(
        self,
        path: str,
        content: bytes,
    ) -> FileResource:
        raise NotImplementedError

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
        raise NotImplementedError

    def delete(
        self,
        path: str,
    ) -> None:
        raise NotImplementedError

    def to_file_resource(self, metadata: dropbox.files.FileMetadata) -> FileResource:
        return FileResource(
            id=metadata.id,
            name=metadata.name,
            path=metadata.path_display,
            size=metadata.size,
            modified_at=metadata.server_modified,
        )