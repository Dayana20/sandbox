from app.errors import FileNotFoundError
from app.models.file import FileResource


class FakeDocumentStorage:

    def __init__(self):
        self.files: dict[str, tuple[FileResource, bytes]] = {}

    def upload(
        self,
        path: str,
        content: bytes,
    ) -> FileResource:

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
        path: str,
        new_path: str,
    ) -> FileResource:

        if path not in self.files:
            raise FileNotFoundError(
                f"File not found: {path}"
            )

        resource, content = self.files.pop(path)

        updated = FileResource(
            id=resource.id,
            name=new_path.split("/")[-1],
            path=new_path,
            size=resource.size,
            modified_at=resource.modified_at,
        )

        self.files[new_path] = (
            updated,
            content,
        )

        return updated

    def delete(
        self,
        path: str,
    ) -> None:

        if path not in self.files:
            raise FileNotFoundError(
                f"File not found: {path}"
            )

        del self.files[path]
