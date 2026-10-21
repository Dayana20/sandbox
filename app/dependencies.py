import functools

import dropbox

from app.cache.cached_storage import CachedDocumentStorage
from app.cache.redis_client import get_redis_client as get_cache_redis_client
from app.core.config import settings
from app.idempotency.redis_client import (
    get_redis_client as get_idempotency_redis_client,
)
from app.idempotency.redis_store import RedisIdempotencyStore
from app.idempotency.service import IdempotencyService
from app.providers.base import DocumentStorage
from app.providers.dropbox.client import create_dropbox_client
from app.providers.dropbox.storage import DropboxStorage


@functools.cache
def get_dropbox_client() -> dropbox.Dropbox:
    # One client for the whole app. A new client per request would have to
    # fetch a fresh access token with the refresh token every time. If the
    # credentials are missing, the error is raised and nothing is cached.
    return create_dropbox_client()


def get_document_storage() -> DocumentStorage:
    storage = DropboxStorage(get_dropbox_client())

    # Metadata caching is on only when REDIS_URL is set and the TTL is above 0.
    # A Redis failure here is ignored: the cache fails open.
    redis_client = get_cache_redis_client()

    if redis_client is None or settings.metadata_cache_ttl_seconds <= 0:
        return storage

    return CachedDocumentStorage(
        storage,
        redis_client,
        settings.metadata_cache_ttl_seconds,
    )


def get_idempotency_service() -> IdempotencyService:
    # Cheap and never touches Redis. Redis is only used when an upload
    # actually sends an Idempotency-Key, and there a Redis failure refuses the
    # upload: idempotency fails closed.
    store = RedisIdempotencyStore(
        get_idempotency_redis_client(),
        settings.idempotency_ttl_seconds,
    )

    return IdempotencyService(store)
