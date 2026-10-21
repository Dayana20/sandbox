from functools import lru_cache

import redis

from app.core.config import settings


@lru_cache(maxsize=1)
def get_redis_client() -> redis.Redis | None:
    """
        Return the shared Redis client, or None when REDIS_URL is not set.

        Creating the client does not connect. It connects on first use, and
        the short timeouts keep a dead Redis from slowing requests down.
    """
    if not settings.redis_url:
        return None

    return redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )
