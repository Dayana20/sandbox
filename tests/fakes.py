from app.errors import (
    FileConflictError,
    FileNotFoundError,
    InvalidOperationError,
)
from app.models.file import FileResource


class FakeDocumentStorage:

    def __init__(self):
        self.files: dict[str, tuple[FileResource, bytes]] = {}
        self.folders: dict[str, FileResource] = {
            "/": FileResource(
                id=None,
                name="",
                path="/",
                size=None,
                modified_at=None,
            )
        }

    def create_folder(self, path: str) -> FileResource:
        """Create an explicit folder for controlled tests."""
        if path in self.files:
            raise FileConflictError(f"File already exists: {path}")
        self._ensure_parent_folders(f"{path}/placeholder")
        folder = self.folders.get(path)
        if folder is None:
            folder = self._folder_resource(path)
            self.folders[path] = folder
        return folder

    def _folder_resource(self, path: str) -> FileResource:
        return FileResource(
            id=path,
            name=path.rsplit("/", maxsplit=1)[-1],
            path=path,
            size=None,
            modified_at=None,
        )

    def _ensure_parent_folders(self, path: str) -> None:
        parts = path.strip("/").split("/")[:-1]
        for index in range(1, len(parts) + 1):
            folder_path = "/" + "/".join(parts[:index])
            self.folders.setdefault(folder_path, self._folder_resource(folder_path))

    def upload(
        self,
        path: str,
        content: bytes,
    ) -> FileResource:

        if path in self.files or path in self.folders:
            raise FileConflictError(
                f"File already exists: {path}"
            )

        self._ensure_parent_folders(path)
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

    def replace(
        self,
        path: str,
        content: bytes,
    ) -> FileResource:

        if path in self.folders:
            raise InvalidOperationError(f"Only files can be replaced: {path}")

        if path not in self.files:
            raise FileNotFoundError(
                f"File not found: {path}"
            )

        resource = self.files[path][0]
        updated = resource.model_copy(update={"size": len(content)})

        self.files[path] = (
            updated,
            content,
        )

        return updated

    def get_metadata(
        self,
        path: str,
    ) -> FileResource:

        if path in self.files:
            return self.files[path][0]
        if path in self.folders:
            return self.folders[path]
        raise FileNotFoundError(f"File not found: {path}")

    def list_files(self, path: str) -> list[FileResource]:
        if path in self.files:
            raise InvalidOperationError(f"Path is not a folder: {path}")
        if path not in self.folders:
            raise FileNotFoundError(f"Folder not found: {path}")

        def parent(resource_path: str) -> str:
            return resource_path.rsplit("/", maxsplit=1)[0] or "/"

        entries = [
            resource.model_copy(update={"type": "file"})
            for resource, _ in self.files.values()
            if parent(resource.path) == path
        ]
        entries.extend(
            resource.model_copy(update={"type": "folder"})
            for folder_path, resource in self.folders.items()
            if folder_path != "/" and parent(folder_path) == path
        )
        return sorted(entries, key=lambda resource: resource.path)

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

        if new_path in self.files or new_path in self.folders:
            raise FileConflictError(
                f"File already exists: {new_path}"
            )

        self._ensure_parent_folders(new_path)
        resource, content = self.files.pop(path)

        updated = FileResource(
            id=resource.id,
            name=new_path.split("/")[-1],
            path=new_path,
            size=resource.size,
            modified_at=resource.modified_at,
            etag=resource.etag,
            type=resource.type,
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

        if path in self.folders:
            # A folder is deleted with everything under it, like Dropbox does.
            prefix = f"{path}/"
            for file_path in [p for p in self.files if p.startswith(prefix)]:
                del self.files[file_path]
            for folder_path in [p for p in self.folders if p.startswith(prefix)]:
                del self.folders[folder_path]
            del self.folders[path]
            return

        if path not in self.files:
            raise FileNotFoundError(
                f"File not found: {path}"
            )

        del self.files[path]
