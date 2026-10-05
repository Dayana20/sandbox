from fastapi import APIRouter, Depends
from app.models.file import FileResource
from app.dependencies import get_document_storage

from app.api.routes.health import router as health_router
from app.api.routes.upload import router as upload_router
from app.api.routes.delete import router as delete_router
from app.providers.dropbox.storage import DropboxStorage


api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(upload_router)
api_router.include_router(delete_router)


@api_router.get("/files/metadata")
def read_metadata(
    path: str,
    storage: DropboxStorage = Depends(get_document_storage),
) -> FileResource:
    '''
    Fetch metadata of a file from cloud storage.
    '''
    return storage.get_metadata(path)
