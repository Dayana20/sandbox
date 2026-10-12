from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.dependencies import get_document_storage
from app.errors import InvalidRequestError
from app.models.file import FileResource
from app.providers.base import DocumentStorage

# Dropbox files_upload accepts up to 150 MB in one request
MAX_UPLOAD_BYTES = 150 * 1024 * 1024

router = APIRouter(
    prefix="/files",
    tags=["files"],
)

def validate_path(path: str | None) -> str:
    if not path:
        raise InvalidRequestError("path is required")

    if not path.startswith("/") or path.endswith("/"):
        raise InvalidRequestError(
            f"path must start with / and end with a file name: {path}"
        )

    for part in path[1:].split("/"):
        if part in ("", ".", ".."):
            raise InvalidRequestError(f"Invalid path: {path}")

    return path


@router.post("", status_code=201)
async def upload_file(
    file: UploadFile | None = File(None),
    path: str | None = Form(None),
    storage: DocumentStorage = Depends(get_document_storage),
) -> FileResource:
    '''
    Upload a new file to cloud storage.
    Returns 409 if a file already exists at the path.
    '''
    if file is None:
        raise InvalidRequestError("file is required")

    path = validate_path(path)
    content = await file.read()

    if len(content) > MAX_UPLOAD_BYTES:
        raise InvalidRequestError("File is larger than 150 MB")

    return storage.upload(path, content)
