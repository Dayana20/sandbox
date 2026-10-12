from fastapi import APIRouter, Depends, Response
from app.dependencies import get_document_storage
from app.errors import InvalidRequestError, FileNotFoundError
from app.models.file import FileResource
from app.providers.base import DocumentStorage

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
    If path is not provided, returns 400.
    Returns 404 if nothing exists at the path.
    '''
    if not path:
        raise InvalidRequestError("path is required")
    # retturn 502 if the provider fails to download
    # include detailed error message in the response
    # include provide error code in the response
    return Response(
        content=storage.download(path)
    )

    # return storage.download(path)