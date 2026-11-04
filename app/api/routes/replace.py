from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.responses import error_responses
from app.api.routes.upload import MAX_UPLOAD_BYTES
from app.dependencies import get_document_storage
from app.errors import InvalidRequestError
from app.models.file import FileResource
from app.providers.base import DocumentStorage
from app.validation import validate_path


router = APIRouter(
    prefix="/files",
    tags=["files"],
)


@router.put("", responses=error_responses(400, 403, 404, 409, 502, 503))
def replace_file(
    file: UploadFile | None = File(None),
    path: str | None = Form(None),
    storage: DocumentStorage = Depends(get_document_storage),
) -> FileResource:
    '''
    Replace the contents of an existing file in cloud storage.
    Returns 404 if nothing exists at the path (replace never creates a file),
    and 409 if the file changed while it was being replaced.
    '''

    if file is None:
        raise InvalidRequestError("file is required")

    path = validate_path(path)

    # Same limit as upload: Dropbox files_upload accepts up to 150 MB
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise InvalidRequestError("File is larger than 150 MB")

    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise InvalidRequestError("File is larger than 150 MB")

    return storage.replace(path, content)
