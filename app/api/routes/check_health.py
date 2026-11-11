from fastapi import APIRouter, Depends
from app.dependencies import get_document_storage
from app.providers.base import DocumentStorage

router = APIRouter(
    prefix="/health",
    tags=["health"],
)


@router.get("/provider")
@router.get("/storage", include_in_schema=False)
def check_health(storage: DocumentStorage = Depends(get_document_storage)) -> dict:
    """
    Check the health of the cloud storage provider.
    Raises an exception if the provider is unreachable or misconfigured.
    Return {"status": "ok"} after storage.check_health() succeeds
    """
    storage.check_health()
    return {"status": "ok"}