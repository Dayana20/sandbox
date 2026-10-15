from fastapi import APIRouter, Depends

from app.api.routes.upload import validate_path
from app.dependencies import get_document_storage
from app.providers.base import DocumentStorage


router = APIRouter(
    prefix="/files",
    tags=["files"],
)


@router.delete("", status_code=204)
def delete_file(
    path: str | None = None,
    storage: DocumentStorage = Depends(get_document_storage),
) -> None:
    '''
    Delete a file from cloud storage.
    Returns 404 if nothing exists at the path, including on a repeated delete.
    '''
    path = validate_path(path)

    storage.delete(path)
