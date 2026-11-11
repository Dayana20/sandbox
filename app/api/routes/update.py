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
    path: str | None = None,
    new_path: str | None = Body(None, embed=True),
    from_path: str | None = None,
    to_path: str | None = Body(None, embed=True),
    storage: DocumentStorage = Depends(get_document_storage),
) -> FileInfo:
    '''
    Rename or move a file in cloud storage.
    Accepts the contract fields ``path`` and ``new_path``. The former
    ``from_path`` and ``to_path`` fields remain supported for compatibility.
    Returns 409 if something already exists at the destination.
    '''
    if path is not None and from_path is not None:
        raise InvalidRequestError("Provide either path or from_path, not both")
    if new_path is not None and to_path is not None:
        raise InvalidRequestError("Provide either new_path or to_path, not both")

    source_path = validate_path(path if path is not None else from_path)
    destination_path = validate_path(
        new_path if new_path is not None else to_path
    )

    # Dropbox paths are case-insensitive and files_move_v2 does not support
    # case-only renames, so "/a.pdf" -> "/A.pdf" is refused here, along with
    # moving a file onto itself, before Dropbox is called.
    if source_path.lower() == destination_path.lower():
        raise InvalidRequestError(
            "destination must differ from source by more than letter case"
        )

    return storage.move(source_path, destination_path)
