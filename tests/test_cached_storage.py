import logging
from unittest.mock import Mock

import fakeredis
import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from app.cache.cached_storage import CachedDocumentStorage, metadata_key
from app.cache.redis_client import get_redis_client
from app.core.config import settings
from app.dependencies import get_document_storage
from app.errors import (
    FileConflictError,
    FileNotFoundError,
    InvalidRequestError,
    PermissionDeniedError,
    ProviderError,
)
from app.main import create_app
from app.models.file import FileResource
from app.providers.dropbox.storage import DropboxStorage
from tests.fakes import FakeDocumentStorage

TTL = 60
PATH = "/docs/report.pdf"


class CountingStorage(FakeDocumentStorage):
    """In-memory storage that counts how often the provider is asked."""

    def __init__(self):
        super().__init__()
        self.metadata_calls = 0
        self.download_calls = 0

    def get_metadata(self, path):
        self.metadata_calls += 1
        return super().get_metadata(path)

    def download(self, path):
        self.download_calls += 1
        return super().download(path)


@pytest.fixture
def redis_client():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def provider():
    storage = CountingStorage()
    storage.upload(PATH, b"hello")

    return storage


@pytest.fixture
def cached(provider, redis_client):
    return CachedDocumentStorage(provider, redis_client, TTL)


# --- hit and miss -----------------------------------------------------------


def test_first_read_is_a_miss_and_fills_the_cache(cached, provider, redis_client):
    assert redis_client.get(metadata_key(PATH)) is None

    resource = cached.get_metadata(PATH)

    assert resource.path == PATH
    assert resource.size == 5
    assert provider.metadata_calls == 1
    assert redis_client.get(metadata_key(PATH)) is not None


def test_second_read_is_a_hit_and_skips_the_provider(cached, provider):
    first = cached.get_metadata(PATH)
    second = cached.get_metadata(PATH)

    assert second == first
    assert provider.metadata_calls == 1


def test_each_path_has_its_own_entry(cached, provider):
    provider.upload("/docs/other.pdf", b"other file")

    cached.get_metadata(PATH)
    other = cached.get_metadata("/docs/other.pdf")

    assert other.size == 10
    assert provider.metadata_calls == 2


def test_cache_key_format(cached, redis_client):
    cached.get_metadata(PATH)

    assert metadata_key(PATH) == "document-storage:metadata:/docs/report.pdf"
    assert redis_client.keys("*") == ["document-storage:metadata:/docs/report.pdf"]


# --- what is not cached -----------------------------------------------------


def test_errors_are_not_cached(cached, provider, redis_client):
    with pytest.raises(FileNotFoundError):
        cached.get_metadata("/docs/missing.pdf")

    assert redis_client.keys("*") == []

    # Once the file exists the next read reaches the provider and succeeds.
    provider.upload("/docs/missing.pdf", b"now here")
    assert cached.get_metadata("/docs/missing.pdf").size == 8
    assert provider.metadata_calls == 2


def test_download_is_never_cached(cached, provider, redis_client):
    assert cached.download(PATH) == b"hello"
    assert cached.download(PATH) == b"hello"

    assert provider.download_calls == 2
    assert redis_client.keys("*") == []


# --- TTL --------------------------------------------------------------------


def test_entries_are_written_with_the_configured_ttl(provider, redis_client):
    CachedDocumentStorage(provider, redis_client, 5).get_metadata(PATH)

    assert 0 < redis_client.ttl(metadata_key(PATH)) <= 5


def test_ttl_of_60_seconds(cached, redis_client):
    cached.get_metadata(PATH)

    assert 0 < redis_client.ttl(metadata_key(PATH)) <= 60


def test_expired_entry_is_read_from_the_provider_again(cached, provider, redis_client):
    cached.get_metadata(PATH)

    # What Redis does when the TTL runs out.
    redis_client.delete(metadata_key(PATH))
    cached.get_metadata(PATH)

    assert provider.metadata_calls == 2


# --- invalidation -----------------------------------------------------------


def test_upload_invalidates_the_path(cached, provider, redis_client):
    cached.get_metadata(PATH)
    assert provider.metadata_calls == 1

    # The file is removed outside our service, so the cached entry is stale.
    del provider.files[PATH]

    cached.upload(PATH, b"a longer replacement")
    assert redis_client.get(metadata_key(PATH)) is None

    # Next read goes to the provider (second call) and sees the new file.
    assert cached.get_metadata(PATH).size == 20
    assert provider.metadata_calls == 2


def test_failed_upload_keeps_the_cache(cached, redis_client):
    cached.get_metadata(PATH)

    with pytest.raises(FileConflictError):
        cached.upload(PATH, b"already exists")

    assert redis_client.get(metadata_key(PATH)) is not None


def test_move_invalidates_old_and_new_paths(cached, provider, redis_client):
    new_path = "/archive/report.pdf"
    cached.get_metadata(PATH)
    # An entry for the destination, as if the file was cached there earlier.
    redis_client.set(metadata_key(new_path), '{"stale": true}', ex=TTL)

    moved = cached.move(PATH, new_path)

    assert moved.path == new_path
    assert redis_client.get(metadata_key(PATH)) is None
    assert redis_client.get(metadata_key(new_path)) is None

    # Old path now reaches the provider and is gone. New path is read fresh.
    calls = provider.metadata_calls
    with pytest.raises(FileNotFoundError):
        cached.get_metadata(PATH)
    assert cached.get_metadata(new_path).path == new_path
    assert provider.metadata_calls == calls + 2


def test_delete_invalidates_the_path(cached, provider, redis_client):
    cached.get_metadata(PATH)
    assert redis_client.get(metadata_key(PATH)) is not None

    cached.delete(PATH)

    assert redis_client.get(metadata_key(PATH)) is None

    calls = provider.metadata_calls
    with pytest.raises(FileNotFoundError):
        cached.get_metadata(PATH)
    assert provider.metadata_calls == calls + 1


def test_failed_delete_keeps_the_cache(cached, redis_client):
    cached.get_metadata(PATH)
    with pytest.raises(FileNotFoundError):
        cached.delete("/docs/missing.pdf")

    assert redis_client.get(metadata_key(PATH)) is not None


# --- Redis failure (fail open) ----------------------------------------------


@pytest.fixture
def broken_redis():
    client = Mock()
    client.get.side_effect = RedisConnectionError("redis is down")
    client.set.side_effect = RedisConnectionError("redis is down")
    client.delete.side_effect = RedisConnectionError("redis is down")

    return client


def test_metadata_still_works_when_redis_is_down(provider, broken_redis, caplog):
    cached = CachedDocumentStorage(provider, broken_redis, TTL)

    with caplog.at_level(logging.WARNING, logger="app.cache.cached_storage"):
        first = cached.get_metadata(PATH)
        second = cached.get_metadata(PATH)

    assert first == second
    assert first.path == PATH
    # No cache, so every read reaches the provider.
    assert provider.metadata_calls == 2
    # Redis failed on the read, so we don't wait on it again to write.
    broken_redis.set.assert_not_called()
    assert "cache_error" in caplog.text
    # Only the exception type is logged, not its message.
    assert "redis is down" not in caplog.text


def test_mutations_still_work_when_redis_is_down(provider, broken_redis):
    cached = CachedDocumentStorage(provider, broken_redis, TTL)

    uploaded = cached.upload("/docs/new.pdf", b"123")
    moved = cached.move("/docs/new.pdf", "/docs/moved.pdf")
    cached.delete("/docs/moved.pdf")

    assert uploaded.path == "/docs/new.pdf"
    assert moved.path == "/docs/moved.pdf"
    assert "/docs/moved.pdf" not in provider.files


def test_provider_errors_still_reach_the_caller_when_redis_is_down(
    provider, broken_redis
):
    cached = CachedDocumentStorage(provider, broken_redis, TTL)

    with pytest.raises(FileNotFoundError):
        cached.get_metadata("/docs/missing.pdf")


def test_unreadable_cache_value_is_treated_as_a_miss(cached, provider, redis_client):
    redis_client.set(metadata_key(PATH), "not json", ex=TTL)

    assert cached.get_metadata(PATH).path == PATH
    assert provider.metadata_calls == 1

    # The bad value was replaced, so the next read is a hit.
    cached.get_metadata(PATH)
    assert provider.metadata_calls == 1


# --- provider failure after the change was attempted -------------------------


class FailingMutationStorage(CountingStorage):
    """Storage whose changing calls raise, like a provider that failed midway."""

    def __init__(self, error: Exception):
        super().__init__()
        self.error = error
        FakeDocumentStorage.upload(self, PATH, b"hello")

    def upload(self, path, content):
        raise self.error

    def move(self, path, new_path):
        raise self.error

    def delete(self, path):
        raise self.error


# A ProviderError and an unexpected exception both leave the outcome unknown.
UNCERTAIN_ERRORS = [
    ProviderError("Dropbox could not complete the call"),
    RuntimeError("connection reset after the request was sent"),
]

# The provider cleanly refused, so nothing changed. (not_found is separate:
# for delete and move it proves the cached source entry is stale.)
CLEAN_REFUSALS = [
    FileConflictError("File already exists"),
    InvalidRequestError("Bad input"),
    PermissionDeniedError("No permission"),
]


def seed_cache(cached, redis_client):
    cached.get_metadata(PATH)
    assert redis_client.get(metadata_key(PATH)) is not None


@pytest.mark.parametrize("error", UNCERTAIN_ERRORS)
def test_upload_failure_invalidates_and_reraises(error, redis_client):
    cached = CachedDocumentStorage(FailingMutationStorage(error), redis_client, TTL)
    seed_cache(cached, redis_client)

    with pytest.raises(type(error)) as exc_info:
        cached.upload(PATH, b"new bytes")

    assert exc_info.value is error
    assert redis_client.get(metadata_key(PATH)) is None


@pytest.mark.parametrize("error", UNCERTAIN_ERRORS)
def test_delete_failure_invalidates_and_reraises(error, redis_client):
    cached = CachedDocumentStorage(FailingMutationStorage(error), redis_client, TTL)
    seed_cache(cached, redis_client)

    with pytest.raises(type(error)) as exc_info:
        cached.delete(PATH)

    assert exc_info.value is error
    assert redis_client.get(metadata_key(PATH)) is None


@pytest.mark.parametrize("error", UNCERTAIN_ERRORS)
def test_move_failure_invalidates_both_paths_and_reraises(error, redis_client):
    new_path = "/archive/report.pdf"
    cached = CachedDocumentStorage(FailingMutationStorage(error), redis_client, TTL)
    seed_cache(cached, redis_client)
    redis_client.set(metadata_key(new_path), '{"stale": true}', ex=TTL)

    with pytest.raises(type(error)) as exc_info:
        cached.move(PATH, new_path)

    assert exc_info.value is error
    assert redis_client.get(metadata_key(PATH)) is None
    assert redis_client.get(metadata_key(new_path)) is None


@pytest.mark.parametrize("error", CLEAN_REFUSALS)
@pytest.mark.parametrize("operation", ["upload", "delete", "move"])
def test_clean_refusal_leaves_the_cache_alone(operation, error, redis_client):
    cached = CachedDocumentStorage(FailingMutationStorage(error), redis_client, TTL)
    seed_cache(cached, redis_client)
    arguments = {
        "upload": (PATH, b"x"),
        "delete": (PATH,),
        "move": (PATH, "/archive/report.pdf"),
    }[operation]

    with pytest.raises(type(error)) as exc_info:
        getattr(cached, operation)(*arguments)

    assert exc_info.value is error
    assert redis_client.get(metadata_key(PATH)) is not None


def test_permission_denied_still_keeps_the_cache_after_not_found_rule(redis_client):
    # Regression: only not_found (and uncertain failures) invalidate.
    error = PermissionDeniedError("No permission")
    cached = CachedDocumentStorage(FailingMutationStorage(error), redis_client, TTL)
    seed_cache(cached, redis_client)

    for call in (
        lambda: cached.delete(PATH),
        lambda: cached.move(PATH, "/archive/report.pdf"),
    ):
        with pytest.raises(PermissionDeniedError) as exc_info:
            call()
        assert exc_info.value is error

    assert redis_client.get(metadata_key(PATH)) is not None


# --- provider confirms the source is missing ----------------------------------


def test_delete_not_found_invalidates_stale_entry_and_reraises(redis_client):
    error = FileNotFoundError("File not found: /docs/report.pdf")
    cached = CachedDocumentStorage(FailingMutationStorage(error), redis_client, TTL)
    seed_cache(cached, redis_client)

    with pytest.raises(FileNotFoundError) as exc_info:
        cached.delete(PATH)

    assert exc_info.value is error
    assert redis_client.get(metadata_key(PATH)) is None


def test_move_source_not_found_invalidates_only_the_source(redis_client):
    new_path = "/archive/report.pdf"
    error = FileNotFoundError("File not found: /docs/report.pdf")
    cached = CachedDocumentStorage(FailingMutationStorage(error), redis_client, TTL)
    seed_cache(cached, redis_client)
    other = FileResource.model_validate_json(redis_client.get(metadata_key(PATH)))
    redis_client.set(metadata_key(new_path), other.model_dump_json(), ex=TTL)

    with pytest.raises(FileNotFoundError) as exc_info:
        cached.move(PATH, new_path)

    assert exc_info.value is error
    assert redis_client.get(metadata_key(PATH)) is None
    # The destination was not what the provider reported missing.
    assert redis_client.get(metadata_key(new_path)) is not None


def test_upload_not_found_keeps_the_cache(redis_client):
    # not_found on upload says nothing about the cached file at that path.
    error = FileNotFoundError("Parent folder not found")
    cached = CachedDocumentStorage(FailingMutationStorage(error), redis_client, TTL)
    seed_cache(cached, redis_client)

    with pytest.raises(FileNotFoundError) as exc_info:
        cached.upload(PATH, b"x")

    assert exc_info.value is error
    assert redis_client.get(metadata_key(PATH)) is not None


@pytest.mark.parametrize("operation", ["delete", "move"])
def test_not_found_cleanup_failure_does_not_hide_the_error(
    operation, broken_redis, caplog
):
    error = FileNotFoundError("File not found")
    cached = CachedDocumentStorage(FailingMutationStorage(error), broken_redis, TTL)
    arguments = {"delete": (PATH,), "move": (PATH, "/archive/report.pdf")}[operation]

    with caplog.at_level(logging.WARNING, logger="app.cache.cached_storage"):
        with pytest.raises(FileNotFoundError) as exc_info:
            getattr(cached, operation)(*arguments)

    assert exc_info.value is error
    assert "cache_error operation=invalidate" in caplog.text


def test_failed_invalidation_does_not_hide_the_provider_error(
    broken_redis, caplog
):
    error = ProviderError("Dropbox could not complete the call")
    cached = CachedDocumentStorage(FailingMutationStorage(error), broken_redis, TTL)

    with caplog.at_level(logging.WARNING, logger="app.cache.cached_storage"):
        with pytest.raises(ProviderError) as exc_info:
            cached.delete(PATH)

    assert exc_info.value is error
    assert "cache_error" in caplog.text


# --- bad cached data ----------------------------------------------------------

BAD_VALUES = [
    "this is not json {",
    '{"id": 1}',
    '{"id": "x", "name": "n", "path": "/p", "size": "big"}',
    "[]",
    "null",
]


@pytest.mark.parametrize("raw", BAD_VALUES)
def test_bad_cached_value_is_a_miss_and_is_refreshed(
    raw, cached, provider, redis_client, caplog
):
    redis_client.set(metadata_key(PATH), raw, ex=TTL)

    with caplog.at_level(logging.INFO, logger="app.cache.cached_storage"):
        result = cached.get_metadata(PATH)

    assert result.path == PATH
    assert provider.metadata_calls == 1
    assert "cache_error" in caplog.text
    # Only the exception type is logged, never what was in Redis.
    assert raw not in caplog.text

    # The bad value was replaced by valid metadata.
    stored = FileResource.model_validate_json(redis_client.get(metadata_key(PATH)))
    assert stored == result

    cached.get_metadata(PATH)
    assert provider.metadata_calls == 1


def test_undecodable_cached_bytes_are_a_miss(cached, provider, redis_client):
    redis_client.set(metadata_key(PATH), b"\xff\xfe\xfd", ex=TTL)

    result = cached.get_metadata(PATH)

    assert result.path == PATH
    assert provider.metadata_calls == 1
    FileResource.model_validate_json(redis_client.get(metadata_key(PATH)))


def test_bad_cached_value_does_not_hide_provider_errors(cached, redis_client):
    redis_client.set(metadata_key("/docs/missing.pdf"), "not json", ex=TTL)

    with pytest.raises(FileNotFoundError):
        cached.get_metadata("/docs/missing.pdf")


# --- path casing -------------------------------------------------------------


class CaseInsensitiveStorage(CountingStorage):
    """Treats paths like Dropbox does: "/Report.pdf" and "/report.pdf" are one file."""

    def upload(self, path, content):
        return super().upload(path.lower(), content)

    def get_metadata(self, path):
        return super().get_metadata(path.lower())

    def download(self, path):
        return super().download(path.lower())

    def move(self, path, new_path):
        return super().move(path.lower(), new_path.lower())

    def delete(self, path):
        return super().delete(path.lower())


@pytest.fixture
def ci_provider():
    storage = CaseInsensitiveStorage()
    storage.upload("/Docs/Report.pdf", b"hello")

    return storage


@pytest.fixture
def ci_cached(ci_provider, redis_client):
    return CachedDocumentStorage(ci_provider, redis_client, TTL)


def test_key_ignores_letter_case():
    assert metadata_key("/Docs/Report.PDF") == metadata_key("/docs/report.pdf")
    assert metadata_key("/Docs/Report.PDF") == "document-storage:metadata:/docs/report.pdf"


def test_equivalent_case_reads_share_one_entry(ci_cached, ci_provider, redis_client):
    first = ci_cached.get_metadata("/Docs/Report.pdf")
    second = ci_cached.get_metadata("/docs/report.pdf")
    third = ci_cached.get_metadata("/DOCS/REPORT.PDF")

    assert first == second == third
    assert ci_provider.metadata_calls == 1
    assert redis_client.keys("*") == ["document-storage:metadata:/docs/report.pdf"]


def test_delete_with_different_case_invalidates(ci_cached, ci_provider, redis_client):
    ci_cached.get_metadata("/Docs/Report.pdf")
    assert redis_client.exists(metadata_key("/Docs/Report.pdf")) == 1

    ci_cached.delete("/docs/report.pdf")

    assert redis_client.keys("*") == []
    with pytest.raises(FileNotFoundError):
        ci_cached.get_metadata("/Docs/Report.pdf")
    assert ci_provider.metadata_calls == 2


def test_upload_with_different_case_invalidates(ci_cached, ci_provider, redis_client):
    ci_cached.get_metadata("/Docs/Report.pdf")
    del ci_provider.files["/docs/report.pdf"]  # removed outside our service

    ci_cached.upload("/DOCS/REPORT.PDF", b"a longer replacement")

    assert redis_client.keys("*") == []
    assert ci_cached.get_metadata("/Docs/Report.pdf").size == 20
    assert ci_provider.metadata_calls == 2


def test_move_with_case_variants_invalidates_both_paths(
    ci_cached, ci_provider, redis_client
):
    ci_cached.get_metadata("/Docs/Report.pdf")
    redis_client.set(metadata_key("/Archive/Report.pdf"), '{"stale": true}', ex=TTL)

    ci_cached.move("/DOCS/REPORT.PDF", "/archive/report.pdf")

    assert redis_client.keys("*") == []

    calls = ci_provider.metadata_calls
    with pytest.raises(FileNotFoundError):
        ci_cached.get_metadata("/docs/report.pdf")
    assert ci_cached.get_metadata("/ARCHIVE/Report.pdf").size == 5
    assert ci_cached.get_metadata("/Archive/report.pdf").size == 5
    assert ci_provider.metadata_calls == calls + 2


def test_provider_still_gets_the_original_path(redis_client):
    seen = []

    class RecordingStorage(CountingStorage):
        def get_metadata(self, path):
            seen.append(path)
            return super().get_metadata(path)

    provider = RecordingStorage()
    provider.upload("/Docs/Report.pdf", b"hello")

    CachedDocumentStorage(provider, redis_client, TTL).get_metadata("/Docs/Report.pdf")

    assert seen == ["/Docs/Report.pdf"]


# --- logging ----------------------------------------------------------------


def test_cache_events_are_logged(cached, caplog):
    with caplog.at_level(logging.INFO, logger="app.cache.cached_storage"):
        cached.get_metadata(PATH)
        cached.get_metadata(PATH)
        cached.delete(PATH)

    for event in ("cache_miss", "cache_write", "cache_hit", "cache_invalidate"):
        assert event in caplog.text


# --- through the HTTP API and the dependency wiring --------------------------


def test_http_metadata_is_served_from_cache(provider, redis_client):
    app = create_app()
    app.dependency_overrides[get_document_storage] = lambda: CachedDocumentStorage(
        provider, redis_client, TTL
    )
    client = TestClient(app)

    first = client.get("/files/metadata", params={"path": PATH})
    second = client.get("/files/metadata", params={"path": PATH})

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["path"] == PATH
    assert provider.metadata_calls == 1


def test_storage_is_not_cached_without_redis_url(monkeypatch):
    monkeypatch.setattr("app.dependencies.create_dropbox_client", lambda: object())

    assert isinstance(get_document_storage(), DropboxStorage)


def test_storage_is_cached_when_redis_url_is_set(monkeypatch):
    fake_client = object()
    monkeypatch.setattr("app.dependencies.create_dropbox_client", lambda: fake_client)
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0")
    monkeypatch.setattr(settings, "metadata_cache_ttl_seconds", 30)
    get_redis_client.cache_clear()

    storage = get_document_storage()

    assert isinstance(storage, CachedDocumentStorage)
    assert isinstance(storage.storage, DropboxStorage)
    assert storage.storage.client is fake_client
    assert storage.ttl_seconds == 30


def test_ttl_of_zero_turns_caching_off(monkeypatch):
    monkeypatch.setattr("app.dependencies.create_dropbox_client", lambda: object())
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0")
    monkeypatch.setattr(settings, "metadata_cache_ttl_seconds", 0)
    get_redis_client.cache_clear()

    assert isinstance(get_document_storage(), DropboxStorage)
