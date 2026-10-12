from fastapi import APIRouter, Depends

from app.api.routes.upload import validate_path
from app.dependencies import get_document_storage
from app.models.file import FileResource
from app.providers.base import DocumentStorage


router = APIRouter(
    prefix="/files",
    tags=["files"],
)


@router.get("/metadata")
def read_metadata(
    path: str | None = None,
    storage: DocumentStorage = Depends(get_document_storage),
) -> FileResource:
    '''
    Get metadata of a file in cloud storage.
    Returns 404 if nothing exists at the path.
    '''
    path = validate_path(path)

    return storage.get_metadata(path)
