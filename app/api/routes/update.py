from fastapi import APIRouter, Body, Depends

from app.api.routes.upload import validate_path
from app.dependencies import get_document_storage
from app.errors import InvalidRequestError
from app.models.file import FileResource
from app.providers.base import DocumentStorage


router = APIRouter(
    prefix="/files",
    tags=["files"],
)


@router.patch("")
def move_file(
    path: str | None = None,
    new_path: str | None = Body(None, embed=True),
    storage: DocumentStorage = Depends(get_document_storage),
) -> FileResource:
    '''
    Rename or move a file in cloud storage.
    Returns 409 if something already exists at new_path.
    '''
    path = validate_path(path)
    new_path = validate_path(new_path)

    # Dropbox paths are case-insensitive and files_move_v2 does not support
    # case-only renames, so "/a.pdf" -> "/A.pdf" is refused here, along with
    # moving a file onto itself, before Dropbox is called.
    if path.lower() == new_path.lower():
        raise InvalidRequestError(
            "new_path must differ from path by more than letter case"
        )

    return storage.move(path, new_path)
