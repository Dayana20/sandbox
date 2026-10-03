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
        raise NotImplementedError

    def download(
        self,
        path: str,
    ) -> bytes:
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