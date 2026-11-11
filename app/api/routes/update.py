from fastapi import APIRouter, Body, Depends

from app.api.responses import error_responses
from app.validation import validate_path
from app.dependencies import get_document_storage
from app.errors import InvalidRequestError
from app.providers.base import DocumentStorage
from cloud_storage_api import FileInfo



router = APIRouter(
    prefix="/files",
    tags=["files"],
)


@router.patch("", responses=error_responses(400, 403, 404, 409, 502, 503))
def move_file(
    from_path: str | None = None,
    to_path: str | None = Body(None, embed=True),
    storage: DocumentStorage = Depends(get_document_storage),
) -> FileInfo:
    '''
    Rename or move a file in cloud storage.
    Returns 409 if something already exists at to_path.
    '''
    from_path = validate_path(from_path)
    to_path = validate_path(to_path)

    # Dropbox paths are case-insensitive and files_move_v2 does not support
    # case-only renames, so "/a.pdf" -> "/A.pdf" is refused here, along with
    # moving a file onto itself, before Dropbox is called.
    if from_path.lower() == to_path.lower():
        raise InvalidRequestError(
            "to_path must differ from from_path by more than letter case"
        )

    return storage.move(from_path, to_path)
