from fastapi import APIRouter, Depends

from app.api.responses import error_responses
from app.dependencies import get_document_storage
from app.models.file import FileResource
from app.providers.base import DocumentStorage
from app.validation import validate_path


router = APIRouter(
    prefix="/files",
    tags=["files"],
)


@router.get(
    "",
    response_model=list[FileResource],
    responses=error_responses(400, 403, 404, 422, 502, 503),
)
def list_files(
    path: str | None = None,
    storage: DocumentStorage = Depends(get_document_storage),
) -> list[FileResource]:
    """Return every direct child of a folder in canonical path order."""
    canonical_path = validate_path(path, allow_root=True)
    return storage.list_files(canonical_path)
