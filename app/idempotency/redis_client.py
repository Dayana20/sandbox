from functools import lru_cache

import redis

from app.core.config import settings


@lru_cache(maxsize=1)
def get_redis_client() -> redis.Redis | None:
    """
        Build the Redis client used for idempotency records.

        Returns None when REDIS_URL is not set. Nothing connects until the
        first command, so building the client never fails because Redis is
        down. decode_responses gives str values instead of bytes.

        The timeouts are longer than a cache needs: here a slow Redis should
        not turn into a refused upload more often than necessary.
    """
    if not settings.redis_url:
        return None

    return redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
