from app.errors import FileConflictError, FileNotFoundError
from app.models.file import FileResource
from cloud_storage_api import FileInfo, ConflictError
from datetime import timezone

class FakeDocumentStorage:

    def __init__(self):
        self.files: dict[str, tuple[FileResource, bytes]] = {}

    def upload(
        self,
        path: str,
        content: bytes,
    ) -> FileResource:

        if path in self.files:
            raise FileConflictError(
                f"File already exists: {path}"
            )

        name = path.split("/")[-1]

        resource = FileResource(
            id=path,
            name=name,
            path=path,
            size=len(content),
            modified_at=None,
        )

        self.files[path] = (
            resource,
            content,
        )

        return resource

    def get_metadata(
        self,
        path: str,
    ) -> FileResource:

        if path not in self.files:
            raise FileNotFoundError(
                f"File not found: {path}"
            )

        return self.files[path][0]

    def download(
        self,
        path: str,
    ) -> bytes:

        if path not in self.files:
            raise FileNotFoundError(
                f"File not found: {path}"
            )

        return self.files[path][1]

    def move(
        self,
        from_path: str,
        to_path: str,
    ) -> FileInfo:

        if from_path not in self.files:
            raise FileNotFoundError(
                f"File not found: {from_path}"
            )

        if to_path in self.files:
            raise ConflictError(
                f"File already exists: {to_path}"
            )

        resource, content = self.files.pop(from_path)

        updated_resource = FileResource(
            id=resource.id,
            name=to_path.split("/")[-1],
            path=to_path,
            size=resource.size,
            modified_at=resource.modified_at,
        )

        self.files[to_path] = (
            updated_resource,
            content,
        )

        modified_at = updated_resource.modified_at
        if modified_at is not None:
            modified_at = modified_at.astimezone(timezone.utc).isoformat()

        return FileInfo(
            id=updated_resource.id,
            name=updated_resource.name,
            path=updated_resource.path,
            size=updated_resource.size,
            modified_at=modified_at,
            etag=None,
            type=None,
        )

    def delete(
        self,
        path: str,
    ) -> None:

        if path not in self.files:
            raise FileNotFoundError(
                f"File not found: {path}"
            )

        del self.files[path]
