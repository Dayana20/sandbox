from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.dependencies import get_document_storage
from app.errors import InvalidRequestError
from app.models.file import FileResource
from app.providers.base import DocumentStorage
from app.validation import validate_path

# Dropbox files_upload accepts up to 150 MB in one request
MAX_UPLOAD_BYTES = 150 * 1024 * 1024

router = APIRouter(
    prefix="/files",
    tags=["files"],
)


@router.post("", status_code=201)
def upload_file(
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
    # After validating the path, check file.size before reading
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise InvalidRequestError("File is larger than 150 MB")

    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise InvalidRequestError("File is larger than 150 MB")

    return storage.upload(path, content)
