import json
import logging
import re
import threading
from unittest.mock import Mock

import fakeredis
import pytest
import redis.exceptions
from fastapi.testclient import TestClient

from app.api.routes import upload
from app.core.config import settings
from app.dependencies import (
    get_document_storage,
    get_idempotency_service,
)
from app.errors import (
    FileConflictError,
    FileNotFoundError,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyOutcomeUnknownError,
    IdempotencyUnavailableError,
    InvalidRequestError,
    PermissionDeniedError,
    ProviderError,
)
from app.idempotency.redis_client import get_redis_client
from app.idempotency.redis_store import (
    KEY_PREFIX,
    RedisIdempotencyStore,
    redis_key,
)
from app.idempotency.service import (
    IdempotencyService,
    hash_key,
    upload_fingerprint,
)
from app.main import create_app
from tests.fakes import FakeDocumentStorage

TTL = 3600
KEY = "abc123"
PATH = "/docs/a.txt"


class CountingStorage(FakeDocumentStorage):
    """Counts every upload the provider is asked to do, even failed ones."""

    def __init__(self):
        super().__init__()
        self.upload_calls = 0

    def upload(self, path, content):
        self.upload_calls += 1
        return super().upload(path, content)


class FailingStorage(CountingStorage):
    """Fails the next upload with `error`, then behaves normally."""

    def __init__(self, error=None):
        super().__init__()
        self.error = error

    def upload(self, path, content):
        if self.error is not None:
            self.upload_calls += 1
            error, self.error = self.error, None
            raise error
        return super().upload(path, content)


class BlockingStorage(CountingStorage):
    """Holds the upload open until the test releases it (no sleeps)."""

    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def upload(self, path, content):
        self.upload_calls += 1
        self.entered.set()
        assert self.release.wait(timeout=10), "test never released the upload"
        return FakeDocumentStorage.upload(self, path, content)


@pytest.fixture
def redis_client():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def broken_redis():
    client = Mock()
    error = redis.exceptions.ConnectionError("redis is down at 10.1.2.3")
    client.set.side_effect = error
    client.get.side_effect = error
    client.delete.side_effect = error

    return client


def make_service(redis_client, ttl=TTL):
    return IdempotencyService(RedisIdempotencyStore(redis_client, ttl))


def make_client(storage, service, raise_server_exceptions=True):
    app = create_app()
    app.dependency_overrides[get_document_storage] = lambda: storage
    app.dependency_overrides[get_idempotency_service] = lambda: service

    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


@pytest.fixture
def storage():
    return CountingStorage()


@pytest.fixture
def client(storage, redis_client):
    return make_client(storage, make_service(redis_client))


def post(client, path=PATH, content=b"hello", key=KEY, filename="a.txt", **headers):
    if key is not None:
        headers["Idempotency-Key"] = key
    data = {} if path is None else {"path": path}

    return client.post(
        "/files",
        data=data,
        files={"file": (filename, content)},
        headers=headers,
    )


def stored_record(redis_client, key=KEY):
    return json.loads(redis_client.get(redis_key(hash_key(key))))


def error_code(response):
    return response.json()["error"]["code"]


# --- first request ------------------------------------------------------------


def test_first_request_uploads_once_and_stores_a_succeeded_record(
    client, storage, redis_client
):
    response = post(client)

    assert response.status_code == 201
    assert response.json()["path"] == PATH
    assert response.json()["size"] == 5
    assert storage.upload_calls == 1

    record = stored_record(redis_client)
    assert record["state"] == "succeeded"
    assert record["fingerprint"] == upload_fingerprint(PATH, b"hello")
    assert record["response"] == response.json()


def test_redis_key_is_namespaced_and_hashed(client, redis_client):
    key = "weird key / with spaces & user@example.com"
    post(client, key=key)

    assert redis_client.keys("*") == [f"{KEY_PREFIX}{hash_key(key)}"]
    assert KEY_PREFIX == "document-storage:idempotency:upload:"
    assert len(hash_key(key)) == 64
    # the caller's value is nowhere in Redis, neither key nor record
    everything = redis_client.keys("*")[0] + redis_client.get(redis_client.keys("*")[0])
    assert "user@example.com" not in everything
    assert key not in everything


# --- replay --------------------------------------------------------------------


def test_replay_returns_the_original_result_without_uploading_again(
    client, storage
):
    first = post(client)
    second = post(client)
    third = post(client)

    assert first.status_code == second.status_code == third.status_code == 201
    assert second.json() == first.json() == third.json()
    assert storage.upload_calls == 1


def test_replay_ignores_the_file_name_the_caller_sends(client, storage):
    # The upload only uses path and bytes, so a different file name is the
    # same request.
    post(client, filename="one.txt")
    again = post(client, filename="two.txt")

    assert again.status_code == 201
    assert storage.upload_calls == 1


def test_different_keys_are_independent(client, storage):
    first = post(client, path="/a.txt", key="key-1")
    second = post(client, path="/b.txt", key="key-2")

    assert first.status_code == second.status_code == 201
    assert storage.upload_calls == 2


# --- conflicting payload -------------------------------------------------------


def test_same_key_with_different_contents_is_a_conflict(client, storage):
    first = post(client, content=b"A")
    second = post(client, content=b"B")

    assert first.status_code == 201
    assert second.status_code == 409
    assert error_code(second) == "idempotency_conflict"
    assert (
        second.json()["error"]["message"]
        == "Idempotency key was already used for a different request"
    )
    assert storage.upload_calls == 1
    assert storage.download(PATH) == b"A"


def test_same_key_with_different_path_is_a_conflict(client, storage):
    post(client, path="/a.txt")
    second = post(client, path="/b.txt")

    assert second.status_code == 409
    assert error_code(second) == "idempotency_conflict"
    assert storage.upload_calls == 1
    assert "/b.txt" not in storage.files


def test_conflict_does_not_leak_fingerprints_or_redis_details(
    client, redis_client
):
    post(client, content=b"A")
    body = post(client, content=b"B").text

    assert upload_fingerprint(PATH, b"A") not in body
    assert upload_fingerprint(PATH, b"B") not in body
    assert hash_key(KEY) not in body
    assert "document-storage" not in body


# --- overlapping requests ------------------------------------------------------


def test_overlapping_request_does_not_call_the_provider(redis_client):
    storage = BlockingStorage()
    client = make_client(storage, make_service(redis_client))
    first_result = []

    def first_request():
        first_result.append(post(client))

    worker = threading.Thread(target=first_request)
    worker.start()
    try:
        # Request A has claimed the key and is inside the provider upload.
        assert storage.entered.wait(timeout=10)

        # Request B: same key, same request.
        overlapping = post(client)

        assert overlapping.status_code == 409
        assert error_code(overlapping) == "idempotency_in_progress"
        assert storage.upload_calls == 1
        assert stored_record(redis_client)["state"] == "in_progress"
    finally:
        storage.release.set()
        worker.join(timeout=10)

    assert first_result[0].status_code == 201
    assert storage.upload_calls == 1
    assert stored_record(redis_client)["state"] == "succeeded"

    # once A finished, B's retry gets A's result
    assert post(client).json() == first_result[0].json()
    assert storage.upload_calls == 1


def test_only_one_of_many_simultaneous_claims_wins(redis_client):
    store = RedisIdempotencyStore(redis_client, TTL)
    fingerprint = upload_fingerprint(PATH, b"hello")
    workers = 20
    barrier = threading.Barrier(workers)
    outcomes = []

    def claim():
        barrier.wait(timeout=10)
        outcomes.append(store.reserve(hash_key(KEY), fingerprint))

    threads = [threading.Thread(target=claim) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    # the winner gets an owner token, the others get the existing record
    winners = [outcome for outcome in outcomes if isinstance(outcome, str)]
    assert len(outcomes) == workers
    assert len(winners) == 1
    losers = [outcome for outcome in outcomes if not isinstance(outcome, str)]
    assert {loser.state for loser in losers} == {"in_progress"}
    assert all(not hasattr(loser, "owner") for loser in losers)


def test_a_stale_in_progress_record_blocks_the_upload(redis_client):
    # A process crashed after claiming the key. Redis still says in_progress.
    # Dropbox may have the file, so the upload must not run again.
    store = RedisIdempotencyStore(redis_client, TTL)
    claimed = store.reserve(hash_key(KEY), upload_fingerprint(PATH, b"hello"))
    assert isinstance(claimed, str)

    storage = CountingStorage()
    client = make_client(storage, make_service(redis_client))
    response = post(client)

    assert response.status_code == 409
    assert error_code(response) == "idempotency_in_progress"
    assert storage.upload_calls == 0


# --- application restart --------------------------------------------------------


def test_stored_result_survives_a_new_service_and_app(redis_client):
    first_storage = CountingStorage()
    first = post(make_client(first_storage, make_service(redis_client)))

    # "Restart": brand new service, store and app. Only Redis is shared.
    second_storage = CountingStorage()
    restarted = make_client(second_storage, make_service(redis_client))
    replay = post(restarted)

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert first_storage.upload_calls == 1
    assert second_storage.upload_calls == 0
    assert PATH not in second_storage.files


def test_conflict_and_uncertain_state_also_survive_a_restart(redis_client):
    failing = FailingStorage(ProviderError("Dropbox is down"))
    post(make_client(failing, make_service(redis_client)))

    restarted_storage = CountingStorage()
    restarted = make_client(restarted_storage, make_service(redis_client))

    assert error_code(post(restarted)) == "idempotency_outcome_unknown"
    assert error_code(post(restarted, content=b"other")) == "idempotency_conflict"
    assert restarted_storage.upload_calls == 0


# --- uncertain provider outcome --------------------------------------------------


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (ProviderError("Dropbox could not upload"), 502, "provider_error"),
        (RuntimeError("connection reset by peer"), 500, "internal_error"),
        # Not something Dropbox upload produces, so we can't call it definitive.
        (FileNotFoundError("File not found"), 404, "not_found"),
    ],
)
def test_any_non_definitive_failure_marks_the_record_uncertain_and_blocks_a_retry(
    error, status, code, redis_client
):
    storage = FailingStorage(error)
    client = make_client(
        storage, make_service(redis_client), raise_server_exceptions=False
    )

    first = post(client)

    # the first caller still gets the original error
    assert first.status_code == status
    assert error_code(first) == code
    assert storage.upload_calls == 1
    assert stored_record(redis_client)["state"] == "uncertain"

    # The provider would work now, but the retry must not reach it.
    retry = post(client)

    assert retry.status_code == 409
    assert error_code(retry) == "idempotency_outcome_unknown"
    assert "may have completed" in retry.json()["error"]["message"]
    assert storage.upload_calls == 1
    assert PATH not in storage.files


def test_a_different_request_after_uncertain_is_a_conflict(redis_client):
    storage = FailingStorage(ProviderError("Dropbox is down"))
    client = make_client(storage, make_service(redis_client))

    post(client)
    other = post(client, content=b"different")

    assert other.status_code == 409
    assert error_code(other) == "idempotency_conflict"
    assert storage.upload_calls == 1


# --- definitive provider failures ----------------------------------------------


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (FileConflictError("File already exists: /docs/a.txt"), 409, "conflict"),
        (InvalidRequestError("Dropbox rejected the request"), 400, "invalid_request"),
        (PermissionDeniedError("No write permission"), 403, "permission_denied"),
    ],
)
def test_definitive_failure_releases_the_key_and_keeps_the_error(
    error, status, code, redis_client
):
    storage = FailingStorage(error)
    client = make_client(storage, make_service(redis_client))

    first = post(client)

    assert first.status_code == status
    assert error_code(first) == code
    assert redis_client.keys("*") == []

    # Dropbox proved nothing was created, so the same key can be used again.
    retry = post(client)

    assert retry.status_code == 201
    assert storage.upload_calls == 2
    assert stored_record(redis_client)["state"] == "succeeded"


def test_existing_file_conflict_through_the_fake_releases_the_key(
    client, storage, redis_client
):
    storage.files[PATH] = (None, b"already there")

    first = post(client, key="key-1")

    assert first.status_code == 409
    assert error_code(first) == "conflict"
    assert redis_client.keys("*") == []


def test_failed_release_does_not_hide_the_provider_error(redis_client):
    class ReleaseFails(RedisIdempotencyStore):
        def release(self, key_hash, owner):
            raise IdempotencyUnavailableError()

    storage = FailingStorage(FileConflictError("File already exists"))
    service = IdempotencyService(ReleaseFails(redis_client, TTL))
    response = post(make_client(storage, service))

    assert response.status_code == 409
    assert error_code(response) == "conflict"


# --- locally rejected requests ------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["", "report.pdf", "/docs/", "//report.pdf", "/docs/../report.pdf"],
)
def test_bad_path_is_rejected_before_idempotency_or_the_provider(
    path, client, storage, redis_client
):
    response = post(client, path=path)

    assert response.status_code == 400
    assert error_code(response) == "invalid_request"
    assert storage.upload_calls == 0
    # nothing was reserved, so nothing can be "uncertain" or "succeeded"
    assert redis_client.keys("*") == []


def test_key_is_reusable_after_a_local_rejection(client, storage, redis_client):
    rejected = post(client, path="docs/no-leading-slash.txt")
    corrected = post(client, path="/docs/fixed.txt")

    assert rejected.status_code == 400
    assert corrected.status_code == 201
    assert storage.upload_calls == 1
    assert stored_record(redis_client)["state"] == "succeeded"


def test_missing_file_and_oversized_file_are_rejected_locally(
    client, storage, redis_client, monkeypatch
):
    no_file = client.post(
        "/files",
        data={"path": PATH},
        headers={"Idempotency-Key": KEY},
    )

    monkeypatch.setattr(upload, "MAX_UPLOAD_BYTES", 10)
    too_big = post(client, content=b"x" * 11)

    assert no_file.status_code == 400
    assert too_big.status_code == 400
    assert storage.upload_calls == 0
    assert redis_client.keys("*") == []


@pytest.mark.parametrize("key", ["", "k" * 256])
def test_bad_key_is_rejected_locally(key, client, storage, redis_client):
    response = post(client, key=key)

    assert response.status_code == 400
    assert error_code(response) == "invalid_request"
    assert "Idempotency-Key" in response.json()["error"]["message"]
    assert storage.upload_calls == 0
    assert redis_client.keys("*") == []


@pytest.mark.parametrize("key", ["k", "k" * 255])
def test_key_length_limits_are_inclusive(key, client, storage):
    assert post(client, key=key).status_code == 201
    assert storage.upload_calls == 1


def test_bad_key_is_rejected_even_when_redis_is_down(
    storage, broken_redis
):
    client = make_client(storage, make_service(broken_redis))

    assert post(client, key="").status_code == 400
    broken_redis.set.assert_not_called()


# --- Redis unavailable (fail closed) -------------------------------------------


def test_redis_down_with_a_key_refuses_the_upload(storage, broken_redis, caplog):
    client = make_client(storage, make_service(broken_redis))

    with caplog.at_level(logging.INFO):
        response = post(client)

    assert response.status_code == 503
    assert error_code(response) == "idempotency_unavailable"
    assert response.json()["error"]["message"] == "Idempotency service is unavailable"
    assert storage.upload_calls == 0
    assert PATH not in storage.files
    # the Redis error text reaches neither the caller nor the log
    assert "10.1.2.3" not in response.text
    assert "redis is down" not in response.text
    assert "redis is down" not in caplog.text
    assert "idempotency_error" in caplog.text
    # Raised from a Redis exception, so it has a __cause__. The shared "cause
    # means provider" rule must not log it as a Dropbox failure.
    assert "error=idempotency_unavailable status=503 provider=no" in caplog.text


def test_redis_not_configured_with_a_key_refuses_the_upload(
    storage, monkeypatch
):
    monkeypatch.setattr(settings, "redis_url", None)
    get_redis_client.cache_clear()
    app = create_app()
    app.dependency_overrides[get_document_storage] = lambda: storage
    # uses the real get_idempotency_service
    client = TestClient(app)

    try:
        response = post(client)
        no_key = post(client, path="/other.txt", key=None)
    finally:
        get_redis_client.cache_clear()

    assert response.status_code == 503
    assert error_code(response) == "idempotency_unavailable"
    assert storage.upload_calls == 1  # only the keyless upload
    assert no_key.status_code == 201


def test_upload_without_a_key_does_not_use_redis(storage, broken_redis):
    client = make_client(storage, make_service(broken_redis))

    response = post(client, key=None)

    assert response.status_code == 201
    assert storage.upload_calls == 1
    # register_script only prepares the script locally (no connection is
    # made). No Redis command may be sent.
    commands = [c for c in broken_redis.mock_calls if c[0] != "register_script"]
    assert commands == []


def test_corrupt_record_refuses_the_upload(storage, redis_client):
    redis_client.set(redis_key(hash_key(KEY)), "not json", ex=TTL)
    client = make_client(storage, make_service(redis_client))

    response = post(client)

    assert response.status_code == 503
    assert error_code(response) == "idempotency_unavailable"
    assert storage.upload_calls == 0


def test_losing_the_record_after_a_good_upload_still_returns_the_result(
    redis_client,
):
    class ExpiringStorage(CountingStorage):
        def upload(self, path, content):
            # the record expires while the provider is working
            redis_client.delete(redis_key(hash_key(KEY)))
            return super().upload(path, content)

    storage = ExpiringStorage()
    client = make_client(storage, make_service(redis_client))

    response = post(client)

    assert response.status_code == 201
    # the expired record is not brought back
    assert redis_client.keys("*") == []


class SaveFailingRedis:
    """
    Real (fake) Redis where only the "save succeeded" write can be made to fail.

    The claim is SET NX and the save is the owner-checked script that writes a
    record with state "succeeded", so the failure can be aimed at the save
    alone. Everything else is passed straight to fakeredis. `events` shows the
    order things happened in.
    """

    def __init__(self, inner, events):
        self.inner = inner
        self.events = events
        self.fail_saves = True

    def set(self, *args, **kwargs):
        if kwargs.get("nx"):
            self.events.append("claim")

        return self.inner.set(*args, **kwargs)

    def register_script(self, script):
        real = self.inner.register_script(script)

        def run(keys, args):
            # args are [owner, new_record, ttl] for the replace script
            is_save = len(args) > 1 and json.loads(args[1])["state"] == "succeeded"
            if is_save and self.fail_saves:
                self.events.append("save failed")
                raise redis.exceptions.ConnectionError("redis is down at 10.1.2.3")

            return real(keys=keys, args=args)

        return run

    def __getattr__(self, name):
        return getattr(self.inner, name)


def test_redis_failing_while_saving_success_keeps_the_201_and_blocks_a_retry(
    redis_client, caplog
):
    key = "secret-customer-key-99"
    contents = b"top secret file contents"
    record_name = redis_key(hash_key(key))
    events = []
    ttl_after_claim = []

    class RecordingStorage(CountingStorage):
        def upload(self, path, content):
            events.append("provider upload")
            ttl_after_claim.append(redis_client.ttl(record_name))
            return super().upload(path, content)

    storage = RecordingStorage()
    flaky = SaveFailingRedis(redis_client, events)
    client = make_client(storage, make_service(flaky))

    with caplog.at_level(logging.INFO, logger="app.idempotency"):
        first = post(client, key=key, content=contents)

    # The claim worked, Dropbox uploaded, and only then did saving fail.
    assert events == ["claim", "provider upload", "save failed"]

    # The upload really happened, so the caller still gets its success.
    assert first.status_code == 201
    assert first.json()["path"] == PATH
    assert first.json()["size"] == len(contents)
    assert storage.upload_calls == 1
    assert storage.download(PATH) == contents

    # The record is NOT marked succeeded. It stays in_progress, with no
    # stored response and no new TTL.
    record = stored_record(redis_client, key)
    assert record["state"] == "in_progress"
    assert "response" not in record
    assert record["fingerprint"] == upload_fingerprint(PATH, contents)
    assert 0 < redis_client.ttl(record_name) <= ttl_after_claim[0] <= TTL

    # The problem is logged, without the key, the contents or Redis's message.
    assert "idempotency_error operation=save_succeeded" in caplog.text
    assert key not in caplog.text
    assert "top secret" not in caplog.text
    assert "10.1.2.3" not in caplog.text
    assert "redis is down" not in caplog.text

    # Redis works again. The same request must not upload a second time.
    flaky.fail_saves = False
    retry = post(client, key=key, content=contents)

    assert retry.status_code == 409
    assert error_code(retry) == "idempotency_in_progress"
    assert storage.upload_calls == 1
    assert stored_record(redis_client, key)["state"] == "in_progress"


# --- reservation ownership ------------------------------------------------------
#
# Request A claims a key and its record expires while A is still running.
# Request B then claims the same key. When A finally finishes, it must not
# change or delete B's record.

FP_A = upload_fingerprint("/docs/a.txt", b"A")
FP_B = upload_fingerprint("/docs/b.txt", b"B")
RESPONSE_A = {
    "id": "id-from-A", "name": "a.txt", "path": "/docs/a.txt",
    "size": 1, "modified_at": None,
}
RESPONSE_B = {
    "id": "id-from-B", "name": "b.txt", "path": "/docs/b.txt",
    "size": 1, "modified_at": None,
}


@pytest.fixture
def store(redis_client):
    return RedisIdempotencyStore(redis_client, TTL)


def claim(store, fingerprint):
    owner = store.reserve(hash_key(KEY), fingerprint)
    assert isinstance(owner, str), "expected to win the claim"

    return owner


def expire(redis_client):
    redis_client.delete(redis_key(hash_key(KEY)))


def two_reservations(store, redis_client, fingerprint_a=FP_A, fingerprint_b=FP_B):
    """A claims, A's record expires, B claims. Returns both owners."""
    owner_a = claim(store, fingerprint_a)
    expire(redis_client)
    owner_b = claim(store, fingerprint_b)
    assert owner_a != owner_b

    return owner_a, owner_b


def test_each_claim_gets_a_unique_opaque_owner_stored_in_the_record(
    store, redis_client
):
    first = store.reserve(hash_key("key-1"), FP_A)
    second = store.reserve(hash_key("key-2"), FP_A)

    assert re.fullmatch(r"[0-9a-f]{32}", first)
    assert re.fullmatch(r"[0-9a-f]{32}", second)
    assert first != second
    assert stored_record(redis_client, "key-1")["owner"] == first

    # a request that finds the key taken gets the record, never the owner
    loser = store.reserve(hash_key("key-1"), FP_A)
    assert not isinstance(loser, str)
    assert not hasattr(loser, "owner")


def test_stale_succeeded_write_does_not_overwrite_a_newer_reservation(
    store, redis_client
):
    owner_a, owner_b = two_reservations(store, redis_client, FP_A, FP_A)
    before = stored_record(redis_client)

    applied = store.save_succeeded(hash_key(KEY), owner_a, FP_A, RESPONSE_A)

    assert applied is False
    assert stored_record(redis_client) == before
    assert before["state"] == "in_progress"
    assert before["owner"] == owner_b
    assert before["fingerprint"] == FP_A
    assert "response" not in before

    # B carries on normally
    assert store.save_succeeded(hash_key(KEY), owner_b, FP_A, RESPONSE_B) is True
    after = stored_record(redis_client)
    assert after["state"] == "succeeded"
    assert after["owner"] == owner_b
    assert after["response"] == RESPONSE_B


def test_stale_succeeded_write_with_a_different_fingerprint_changes_nothing(
    store, redis_client
):
    owner_a, owner_b = two_reservations(store, redis_client, FP_A, FP_B)

    applied = store.save_succeeded(hash_key(KEY), owner_a, FP_A, RESPONSE_A)

    record = stored_record(redis_client)
    assert applied is False
    assert record["fingerprint"] == FP_B
    assert record["owner"] == owner_b
    assert record["state"] == "in_progress"
    assert "response" not in record
    assert "id-from-A" not in redis_client.get(redis_key(hash_key(KEY)))

    # a request repeating A now sees B's reservation, not A's result
    seen = store.reserve(hash_key(KEY), FP_A)
    assert seen.fingerprint == FP_B

    assert store.save_succeeded(hash_key(KEY), owner_b, FP_B, RESPONSE_B) is True
    assert stored_record(redis_client)["response"] == RESPONSE_B


@pytest.mark.parametrize(
    "stale_change",
    [
        pytest.param(lambda s, owner: s.mark_uncertain(hash_key(KEY), owner, FP_A), id="mark_uncertain"),
        pytest.param(lambda s, owner: s.release(hash_key(KEY), owner), id="release"),
    ],
)
def test_stale_uncertain_or_release_leaves_the_newer_record_alone(
    stale_change, store, redis_client
):
    owner_a, owner_b = two_reservations(store, redis_client)
    before = stored_record(redis_client)

    assert stale_change(store, owner_a) is False

    # not marked uncertain, not deleted: B's record is exactly as B made it
    assert redis_client.exists(redis_key(hash_key(KEY))) == 1
    assert stored_record(redis_client) == before
    assert before["state"] == "in_progress"
    assert before["owner"] == owner_b
    assert before["fingerprint"] == FP_B


def test_current_owner_can_save_succeeded(store, redis_client):
    owner = claim(store, FP_A)

    assert store.save_succeeded(hash_key(KEY), owner, FP_A, RESPONSE_A) is True

    record = stored_record(redis_client)
    assert record == {
        "state": "succeeded",
        "fingerprint": FP_A,
        "owner": owner,
        "response": RESPONSE_A,
    }
    assert 0 < redis_client.ttl(redis_key(hash_key(KEY))) <= TTL


def test_current_owner_can_mark_uncertain(store, redis_client):
    owner = claim(store, FP_A)

    assert store.mark_uncertain(hash_key(KEY), owner, FP_A) is True

    record = stored_record(redis_client)
    assert record == {"state": "uncertain", "fingerprint": FP_A, "owner": owner}
    assert 0 < redis_client.ttl(redis_key(hash_key(KEY))) <= TTL


def test_current_owner_can_release(store, redis_client):
    owner = claim(store, FP_A)

    assert store.release(hash_key(KEY), owner) is True

    assert redis_client.keys("*") == []
    # the key is free again
    assert isinstance(store.reserve(hash_key(KEY), FP_A), str)


def test_stale_owner_does_not_recreate_an_expired_record(store, redis_client):
    owner = claim(store, FP_A)
    expire(redis_client)

    assert store.save_succeeded(hash_key(KEY), owner, FP_A, RESPONSE_A) is False
    assert store.mark_uncertain(hash_key(KEY), owner, FP_A) is False
    assert store.release(hash_key(KEY), owner) is False

    assert redis_client.keys("*") == []


def test_an_unreadable_record_is_not_touched_by_a_transition(store, redis_client):
    name = redis_key(hash_key(KEY))
    redis_client.set(name, "not json", ex=TTL)

    assert store.save_succeeded(hash_key(KEY), "owner", FP_A, RESPONSE_A) is False
    assert store.mark_uncertain(hash_key(KEY), "owner", FP_A) is False
    assert store.release(hash_key(KEY), "owner") is False

    assert redis_client.get(name) == "not json"


@pytest.mark.parametrize(
    ("newer_claim", "reason"),
    [(False, "record_missing"), (True, "owner_changed")],
)
def test_skipped_update_is_logged_without_secrets(
    newer_claim, reason, store, redis_client, caplog
):
    owner_a = claim(store, FP_A)
    expire(redis_client)
    owner_b = claim(store, FP_B) if newer_claim else ""

    with caplog.at_level(logging.INFO, logger="app.idempotency"):
        store.save_succeeded(hash_key(KEY), owner_a, FP_A, RESPONSE_A)
        store.mark_uncertain(hash_key(KEY), owner_a, FP_A)
        store.release(hash_key(KEY), owner_a)

    key_id = hash_key(KEY)[:12]
    for operation, transition in (
        ("save_succeeded", "in_progress->succeeded"),
        ("mark_uncertain", "in_progress->uncertain"),
        ("release", "in_progress->released"),
    ):
        assert (
            f"idempotency_state_update_skipped operation={operation} "
            f"transition={transition} reason={reason} key_id={key_id}"
        ) in caplog.text

    # no owner token, fingerprint, response data or raw key in the log
    for secret in (owner_a, owner_b, FP_A, FP_B, "id-from-A", KEY):
        if secret:
            assert secret not in caplog.text


def test_ownership_checks_run_inside_redis_not_as_get_then_set(redis_client):
    """The owner check and the change are one script, not Python GET + SET/DEL."""

    class SpyRedis:
        def __init__(self, inner):
            self.inner = inner
            self.python_side_calls = []

        def __getattr__(self, name):
            # Fetching one of these to call it is a Python-side Redis command.
            if name in ("get", "set", "delete", "pipeline"):
                self.python_side_calls.append(name)
            return getattr(self.inner, name)

    spy = SpyRedis(redis_client)
    store = RedisIdempotencyStore(spy, TTL)

    for transition in ("save", "uncertain", "release"):
        owner = store.reserve(hash_key(transition), FP_A)
        assert isinstance(owner, str)
        spy.python_side_calls.clear()

        if transition == "save":
            assert store.save_succeeded(hash_key(transition), owner, FP_A, RESPONSE_A)
        elif transition == "uncertain":
            assert store.mark_uncertain(hash_key(transition), owner, FP_A)
        else:
            assert store.release(hash_key(transition), owner)

        assert spy.python_side_calls == [], transition


class TakeoverStorage(CountingStorage):
    """
    While A's upload is running, A's record expires and request B claims the
    key. Then A's upload finishes (or fails with `error`).
    """

    def __init__(self, redis_client, error=None):
        super().__init__()
        self.redis_client = redis_client
        self.error = error
        self.b_owner = None
        self.b_record = None

    def upload(self, path, content):
        self.upload_calls += 1
        expire(self.redis_client)
        claimed = RedisIdempotencyStore(self.redis_client, TTL).reserve(
            hash_key(KEY), FP_B
        )
        assert isinstance(claimed, str)
        self.b_owner = claimed
        self.b_record = stored_record(self.redis_client)
        if self.error is not None:
            raise self.error

        return FakeDocumentStorage.upload(self, path, content)


def test_late_success_returns_201_but_leaves_the_newer_reservation(
    redis_client, caplog
):
    storage = TakeoverStorage(redis_client)
    client = make_client(storage, make_service(redis_client))

    with caplog.at_level(logging.INFO, logger="app.idempotency"):
        response = post(client)

    assert response.status_code == 201
    assert response.json()["path"] == PATH
    assert storage.upload_calls == 1
    # B's record is exactly as B created it
    assert stored_record(redis_client) == storage.b_record
    assert storage.b_record["state"] == "in_progress"
    assert storage.b_record["fingerprint"] == FP_B
    assert (
        "idempotency_state_update_skipped operation=save_succeeded" in caplog.text
    )
    assert "reason=owner_changed" in caplog.text
    assert storage.b_owner not in caplog.text
    assert storage.b_owner not in response.text


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        # uncertain: would normally mark the record uncertain
        (ProviderError("Dropbox is down"), 502, "provider_error"),
        # definitive: would normally release the record
        (FileConflictError("File already exists"), 409, "conflict"),
        (InvalidRequestError("Dropbox rejected the request"), 400, "invalid_request"),
        (PermissionDeniedError("No write permission"), 403, "permission_denied"),
    ],
)
def test_late_failure_returns_the_original_error_and_leaves_the_newer_record(
    error, status, code, redis_client
):
    storage = TakeoverStorage(redis_client, error=error)
    client = make_client(storage, make_service(redis_client))

    response = post(client)

    assert response.status_code == status
    assert error_code(response) == code
    assert storage.upload_calls == 1
    assert redis_client.exists(redis_key(hash_key(KEY))) == 1
    assert stored_record(redis_client) == storage.b_record


def test_owner_token_never_reaches_the_caller_or_the_log(
    client, redis_client, caplog
):
    with caplog.at_level(logging.INFO, logger="app.idempotency"):
        first = post(client)
        owner = stored_record(redis_client)["owner"]
        replay = post(client)
        conflict = post(client, content=b"different")

    assert owner not in caplog.text
    for response in (first, replay, conflict):
        assert owner not in response.text
        assert "owner" not in response.text


# --- retention (TTL) -----------------------------------------------------------


def test_records_get_the_configured_ttl_in_every_state(redis_client):
    redis_key_name = redis_key(hash_key(KEY))
    seen = {}

    class InspectingStorage(CountingStorage):
        def upload(self, path, content):
            seen["in_progress"] = redis_client.ttl(redis_key_name)
            return super().upload(path, content)

    client = make_client(InspectingStorage(), make_service(redis_client, ttl=TTL))
    post(client)
    seen["succeeded"] = redis_client.ttl(redis_key_name)

    uncertain_client = make_client(
        FailingStorage(ProviderError("down")),
        make_service(redis_client, ttl=TTL),
    )
    post(uncertain_client, key="other-key")
    seen["uncertain"] = redis_client.ttl(redis_key(hash_key("other-key")))

    for state, ttl in seen.items():
        assert 0 < ttl <= TTL, state
        assert ttl > TTL - 60, state


def test_ttl_comes_from_the_setting_and_defaults_to_24_hours():
    assert settings.idempotency_ttl_seconds == 86400


def test_an_expired_record_means_the_key_is_a_new_request(
    storage, redis_client
):
    client = make_client(storage, make_service(redis_client))
    post(client)

    # Retention ended (what Redis does when the TTL runs out).
    redis_client.delete(redis_key(hash_key(KEY)))
    after_expiry = post(client, path="/docs/b.txt")

    assert after_expiry.status_code == 201
    assert storage.upload_calls == 2


def test_get_idempotency_service_uses_the_configured_ttl(monkeypatch):
    monkeypatch.setattr(settings, "idempotency_ttl_seconds", 123)

    service = get_idempotency_service()

    assert service.store.ttl_seconds == 123  # type: ignore[attr-defined]


# --- uploads without a key ------------------------------------------------------


def test_upload_without_a_key_behaves_as_before(storage, redis_client):
    service = Mock()
    client = make_client(storage, service)

    first = post(client, key=None)
    second = post(client, key=None)

    assert first.status_code == 201
    assert second.status_code == 409
    assert error_code(second) == "conflict"
    assert storage.upload_calls == 2
    assert service.mock_calls == []
    assert redis_client.keys("*") == []


# --- fingerprint and key hashing -------------------------------------------------


def test_fingerprint_is_deterministic():
    assert upload_fingerprint("/a", b"x") == upload_fingerprint("/a", b"x")
    assert len(upload_fingerprint("/a", b"x")) == 64


@pytest.mark.parametrize(
    ("path", "content"),
    [("/b", b"x"), ("/a", b"y"), ("/a", b""), ("/a/", b"x")],
)
def test_fingerprint_changes_with_path_or_contents(path, content):
    assert upload_fingerprint(path, content) != upload_fingerprint("/a", b"x")


def test_fingerprint_does_not_depend_on_where_path_and_contents_meet():
    # With naive concatenation, ("/ab", b"c") and ("/a", b"bc") would clash.
    assert upload_fingerprint("/ab", b"c") != upload_fingerprint("/a", b"bc")


def test_hash_key_is_sha256_of_the_key():
    assert hash_key("abc123") == (
        "6ca13d52ca70c883e0f0bb101e425a89e8624de51db2d2392593af6a84118090"
    )


# --- logging -----------------------------------------------------------------


def test_events_are_logged_without_the_raw_key_contents_or_path(
    storage, redis_client, caplog
):
    key = "secret-customer-key-42"
    secret_bytes = b"top secret file contents"
    private = "/private-folder/secret-report.pdf"
    client = make_client(storage, make_service(redis_client))

    # root logger: also covers milestone-3's request_failed line for the 409
    with caplog.at_level(logging.DEBUG):
        post(client, path=private, key=key, content=secret_bytes)  # reserved
        post(client, path=private, key=key, content=secret_bytes)  # replay
        post(client, path=private, key=key, content=b"other")  # conflict

    for event in (
        "idempotency_reserved",
        "idempotency_replay",
        "idempotency_conflict",
        "request_failed",
    ):
        assert event in caplog.text, event

    assert hash_key(key)[:12] in caplog.text
    for secret in (key, "top secret", private, "private-folder", "secret-report"):
        assert secret not in caplog.text, secret


def test_in_progress_and_uncertain_events_are_logged(redis_client, caplog):
    store = RedisIdempotencyStore(redis_client, TTL)
    store.reserve(hash_key("busy"), upload_fingerprint(PATH, b"hello"))
    client = make_client(CountingStorage(), make_service(redis_client))
    failing_client = make_client(
        FailingStorage(ProviderError("down")), make_service(redis_client)
    )

    with caplog.at_level(logging.INFO, logger="app.idempotency"):
        post(client, key="busy")
        post(failing_client, key="unsure")
        post(failing_client, key="unsure")

    assert "idempotency_in_progress" in caplog.text
    assert "idempotency_uncertain" in caplog.text
    assert "busy" not in caplog.text
    assert "unsure" not in caplog.text


# --- milestone-3 error handling and logging rules ---------------------------------


@pytest.mark.parametrize(
    "error, status, code",
    [
        (IdempotencyConflictError, 409, "idempotency_conflict"),
        (IdempotencyInProgressError, 409, "idempotency_in_progress"),
        (IdempotencyOutcomeUnknownError, 409, "idempotency_outcome_unknown"),
        (IdempotencyUnavailableError, 503, "idempotency_unavailable"),
    ],
)
def test_idempotency_errors_use_the_shared_error_style_and_are_never_a_500(
    error, status, code, storage, caplog
):
    service = Mock()
    service.run_upload.side_effect = error()
    # raise_server_exceptions=False: a catch-all 500 must show up as a 500
    # here instead of being re-raised into the test.
    client = make_client(storage, service, raise_server_exceptions=False)

    with caplog.at_level(logging.INFO):
        response = post(client, **{"X-Request-ID": "trace-me-123"})

    assert response.status_code == status
    assert set(response.json()) == {"error"}
    assert set(response.json()["error"]) == {"code", "message"}
    assert error_code(response) == code
    assert response.json()["error"]["message"] == error.message
    assert response.headers["X-Request-ID"] == "trace-me-123"
    assert "internal_error" not in caplog.text
    assert (
        f"request_failed operation=upload_file error={code} status={status} "
        "provider=no request_id=trace-me-123"
    ) in caplog.text
    assert storage.upload_calls == 0
