import pytest

from app.cache.redis_client import get_redis_client
from app.core.config import settings
from app.dependencies import get_dropbox_client


@pytest.fixture(autouse=True)
def no_redis_by_default(monkeypatch):
    # A REDIS_URL in a developer's .env must not change the fast tests.
    # Tests that need a cache pass in a fake Redis themselves.
    monkeypatch.setattr(settings, "redis_url", None)
    # Both clients are cached for the life of the app, so reset them around
    # every test. Otherwise one test's fake Dropbox client leaks into the next.
    get_redis_client.cache_clear()
    get_dropbox_client.cache_clear()

    yield

    get_redis_client.cache_clear()
    get_dropbox_client.cache_clear()
