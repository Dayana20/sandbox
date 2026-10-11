from fastapi import APIRouter

from app.api.routes.delete import router as delete_router
from app.api.routes.health import router as health_router
from app.api.routes.read import router as read_router
from app.api.routes.update import router as update_router
from app.api.routes.upload import router as upload_router


api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(upload_router)
api_router.include_router(read_router)
api_router.include_router(update_router)
api_router.include_router(delete_router)
