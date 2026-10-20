from app.core.config import settings
from app.idempotency.redis_client import get_redis_client
from app.idempotency.redis_store import RedisIdempotencyStore
from app.idempotency.service import IdempotencyService
from app.providers.base import DocumentStorage
from app.providers.dropbox.client import create_dropbox_client
from app.providers.dropbox.storage import DropboxStorage


def get_document_storage() -> DocumentStorage:
    client = create_dropbox_client()

    return DropboxStorage(client)


def get_idempotency_service() -> IdempotencyService:
    # Cheap and never touches Redis. Redis is only used when an upload
    # actually sends an Idempotency-Key.
    store = RedisIdempotencyStore(
        get_redis_client(),
        settings.idempotency_ttl_seconds,
    )

    return IdempotencyService(store)
