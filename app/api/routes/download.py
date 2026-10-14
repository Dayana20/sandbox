from fastapi import APIRouter, Depends, Response

from app.dependencies import get_document_storage
from app.providers.base import DocumentStorage
from app.validation import validate_path

# Dropbox has no max cap to download
router = APIRouter(
    prefix="/files",
    tags=["files"],
)


@router.get("/download")
def download_file(
    path: str | None = None,
    storage: DocumentStorage = Depends(get_document_storage),
) -> Response:
    '''
    Download a file from cloud storage.
    Returns 400 for a missing or bad path, 404 if nothing exists at the path.
    '''
    path = validate_path(path)

    return Response(
        content=storage.download(path)
    )
