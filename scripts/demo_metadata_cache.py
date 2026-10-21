"""
Show the metadata cache working against a real Redis and a real Dropbox.

Start Redis first:
    docker run --rm -p 6379:6379 redis:7-alpine

Then run:
    python -m scripts.demo_metadata_cache

Uses REDIS_URL from .env (default redis://localhost:6379/0) and writes one
small file under /integration-tests/, which it deletes at the end.
"""
import uuid

import redis

from app.cache.cached_storage import CachedDocumentStorage, metadata_key
from app.core.config import settings
from app.errors import FileNotFoundError
from app.providers.dropbox.client import create_dropbox_client
from app.providers.dropbox.storage import DropboxStorage

TTL_SECONDS = 60


class CountingStorage(DropboxStorage):
    """DropboxStorage that counts how often Dropbox is asked for metadata."""

    metadata_calls = 0

    def get_metadata(self, path):
        self.metadata_calls += 1
        return super().get_metadata(path)


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

    provider = CountingStorage(create_dropbox_client())
    storage = CachedDocumentStorage(provider, redis_client, TTL_SECONDS)

    folder = f"/integration-tests/cache-demo-{uuid.uuid4().hex}"
    old_path = f"{folder}/original.txt"
    new_path = f"{folder}/renamed.txt"
    failures = []

    def read(step: str, path: str, expect_state: str, expect_calls: int) -> None:
        state = "HIT" if redis_client.exists(metadata_key(path)) else "MISS"
        try:
            storage.get_metadata(path)
            result = "found"
        except FileNotFoundError:
            result = "not found"
        print(
            f"{step:<34} cache={state:<4} provider metadata calls={provider.metadata_calls}"
            f"  ({result})"
        )
        if state != expect_state or provider.metadata_calls != expect_calls:
            failures.append(step)

    def key_present(path: str) -> bool:
        return bool(redis_client.exists(metadata_key(path)))

    print(f"Redis: {url}   TTL: {TTL_SECONDS}s   Dropbox folder: {folder}\n")

    try:
        storage.upload(old_path, b"cache demo")
        print("upload original.txt                (invalidates its cache entry)")

        read("1. read original.txt", old_path, "MISS", 1)
        read("2. read original.txt again", old_path, "HIT", 1)
        print(f"   cached TTL left: {redis_client.ttl(metadata_key(old_path))}s")

        storage.move(old_path, new_path)
        print("3. move original.txt -> renamed.txt (invalidates both paths)")
        print(f"   original cached: {key_present(old_path)}   renamed cached: {key_present(new_path)}")
        if key_present(old_path) or key_present(new_path):
            failures.append("invalidate after move")

        read("4. read renamed.txt", new_path, "MISS", 2)
        read("5. read renamed.txt again", new_path, "HIT", 2)

        storage.delete(new_path)
        print("6. delete renamed.txt              (invalidates its cache entry)")
        print(f"   renamed cached: {key_present(new_path)}")
        if key_present(new_path):
            failures.append("invalidate after delete")

        read("7. read renamed.txt after delete", new_path, "MISS", 3)
    finally:
        # Remove anything left in Dropbox or Redis.
        for path in (old_path, new_path):
            redis_client.delete(metadata_key(path))
        try:
            provider.client.files_delete_v2(folder)
        except Exception:
            pass

    print()
    if failures:
        raise SystemExit(f"DEMO FAILED at: {', '.join(failures)}")

    print("Caching works: 2 hits served without calling Dropbox, 3 misses called it.")


if __name__ == "__main__":
    main()
