"""
Show upload idempotency working against a real Redis and a real Dropbox.

Start Redis first:
    docker run --rm -p 6379:6379 redis:7-alpine

Then run:
    python -m scripts.demo_idempotency

Uses REDIS_URL from .env (default redis://localhost:6379/0). It uploads one
small file under /integration-tests/ and deletes the file and the Redis
record at the end. The Idempotency-Key is random and is never printed.
"""
import json
import uuid

import redis
from fastapi.testclient import TestClient

from app.core.config import settings
from app.dependencies import get_document_storage, get_idempotency_service
from app.idempotency.redis_store import RedisIdempotencyStore, redis_key
from app.idempotency.service import IdempotencyService, hash_key
from app.main import create_app
from app.providers.dropbox.client import create_dropbox_client
from app.providers.dropbox.storage import DropboxStorage

TTL_SECONDS = 300


class CountingStorage(DropboxStorage):
    """DropboxStorage that counts how often Dropbox is asked to upload."""

    upload_calls = 0

    def upload(self, path, content):
        self.upload_calls += 1
        return super().upload(path, content)


def main() -> None:
    url = settings.redis_url or "redis://localhost:6379/0"
    redis_client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2)

    try:
        redis_client.ping()
    except redis.exceptions.RedisError:
        raise SystemExit(
            "Cannot reach Redis. Start it with:\n"
            "  docker run --rm -p 6379:6379 redis:7-alpine"
        )

    dropbox_client = create_dropbox_client()
    provider = CountingStorage(dropbox_client)

    def make_http_client(client: redis.Redis) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_document_storage] = lambda: provider
        service = IdempotencyService(RedisIdempotencyStore(client, TTL_SECONDS))
        app.dependency_overrides[get_idempotency_service] = lambda: service

        return TestClient(app)

    key = f"demo-key-{uuid.uuid4().hex}"
    record_key = redis_key(hash_key(key))
    folder = f"/integration-tests/idempotency-demo-{uuid.uuid4().hex}"
    path = f"{folder}/report.txt"
    payload_a = b"payload A"
    payload_b = b"payload B (different)"
    failures: list[str] = []

    print(f"Redis: {url}   TTL: {TTL_SECONDS}s   Dropbox folder: {folder}")
    print(f"key id (first 12 chars of SHA-256): {hash_key(key)[:12]}")

    def post(http: TestClient, step: str, content: bytes, expect_status: int,
             expect_code: str | None, expect_calls: int) -> None:
        response = http.post(
            "/files",
            data={"path": path},
            files={"file": ("report.txt", content)},
            headers={"Idempotency-Key": key},
        )
        body = response.json()
        code = body.get("error", {}).get("code") if "error" in body else None
        outcome = f"{response.status_code} {code or 'created'}"
        print(f"{step:<46} -> {outcome:<34} Dropbox upload calls={provider.upload_calls}")

        if response.status_code != expect_status or code != expect_code:
            failures.append(f"{step}: got {outcome}")
        if provider.upload_calls != expect_calls:
            failures.append(f"{step}: provider calls {provider.upload_calls}, expected {expect_calls}")

    def show_record() -> None:
        raw = redis_client.get(record_key)
        if raw is None:
            print("   Redis record: none")
            return
        state = json.loads(raw)["state"]
        print(f"   Redis record: state={state}  ttl={redis_client.ttl(record_key)}s")

    try:
        http = make_http_client(redis_client)

        post(http, "1. payload A, new key", payload_a, 201, None, 1)
        show_record()
        post(http, "2. payload A again (replay)", payload_a, 201, None, 1)
        post(http, "3. payload B, same key", payload_b, 409, "idempotency_conflict", 1)

        # a new app and service over the same Redis: the "restart"
        post(make_http_client(redis_client), "4. payload A after a restart", payload_a, 201, None, 1)

        # a Redis that cannot be reached: the request must be refused
        dead = redis.Redis.from_url(
            "redis://127.0.0.1:1/0",
            decode_responses=True,
            socket_connect_timeout=1,
        )
        post(make_http_client(dead), "5. Redis unreachable (fail closed)", payload_a, 503, "idempotency_unavailable", 1)

        _, downloaded = dropbox_client.files_download(path)
        if downloaded.content != payload_a:
            failures.append("the file in Dropbox does not hold payload A")
        else:
            print("Dropbox file holds payload A (payload B never reached Dropbox)")
    finally:
        try:
            dropbox_client.files_delete_v2(folder)
        except Exception:
            pass
        redis_client.delete(record_key)

    gone = redis_client.exists(record_key) == 0
    print(f"cleanup: Redis record removed={gone}, Dropbox folder deleted")

    if failures or not gone:
        print("\nDEMO FAILED at:")
        for failure in failures:
            print(f"  {failure}")
        raise SystemExit(1)

    print("\nIdempotency works: 5 requests, Dropbox was asked to upload exactly once.")


if __name__ == "__main__":
    main()
