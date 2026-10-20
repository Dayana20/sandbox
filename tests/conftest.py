import pytest

from app.cache.redis_client import get_redis_client
from app.core.config import settings


@pytest.fixture(autouse=True)
def no_redis_by_default(monkeypatch):
    # A REDIS_URL in a developer's .env must not change the fast tests.
    # Tests that need a cache pass in a fake Redis themselves.
    monkeypatch.setattr(settings, "redis_url", None)
    get_redis_client.cache_clear()

    yield

    get_redis_client.cache_clear()
