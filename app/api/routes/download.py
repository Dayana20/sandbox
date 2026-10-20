from fastapi import APIRouter, Depends, Response

from app.api.responses import error_responses
from app.dependencies import get_document_storage
from app.providers.base import DocumentStorage
from app.validation import validate_path
from urllib.parse import quote

# Dropbox has no max cap to download
router = APIRouter(
    prefix="/files",
    tags=["files"],
)


@router.get("/download", responses=error_responses(400, 403, 404, 502, 503))
def download_file(
    path: str | None = None,
    storage: DocumentStorage = Depends(get_document_storage),
) -> Response:
    '''
    Download a file from cloud storage.
    Returns 400 for a missing or bad path, 404 if nothing exists at the path.
    '''
    path = validate_path(path)

    filename = path.rsplit("/", maxsplit=1)[-1]
    ascii_filename = "".join(
        char if 0x20 <= ord(char) <= 0x7E and char not in {'"', "\\"} else "_"
        for char in filename
    )
    encoded_filename = quote(filename, safe="!#$&+-.^_`|~")

    return Response(
        content=storage.download(path),
        media_type="application/octet-stream",
        headers={"Content-Disposition": (
            f'attachment; filename="{ascii_filename}";'
            f"filename*=UTF-8''{encoded_filename}"
        )}
    )
