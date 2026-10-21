import hashlib
import logging
from collections.abc import Callable
from typing import TypeVar

import redis
from redis.exceptions import RedisError

from app.errors import FileNotFoundError, ProviderError, StorageError
from app.models.file import FileResource
from app.providers.base import DocumentStorage

logger = logging.getLogger(__name__)

KEY_PREFIX = "document-storage:metadata:"

T = TypeVar("T")


def metadata_key(path: str) -> str:
    # Dropbox treats "/Report.pdf" and "/report.pdf" as the same file, so both
    # must share one cache entry. Only the key is lower-cased. The provider is
    # still called with the path exactly as the caller sent it.
    return f"{KEY_PREFIX}{path.lower()}"


def key_id(path: str) -> str:
    # File paths are never logged, because file names can be private. Logs show
    # this short one-way id instead. It is built from the same lower-cased path
    # as the cache key, so every spelling of one file logs the same id.
    return hashlib.sha256(path.lower().encode()).hexdigest()[:12]


class CachedDocumentStorage:
    """
        Adds a Redis cache for get_metadata to any DocumentStorage.

        Cache-aside: read Redis first, on a miss ask the wrapped storage and
        store the answer for ttl_seconds. Only successful metadata is cached.
        Errors and file bytes are never cached.

        upload, move and delete go to the wrapped storage first, then the
        cached entries for the paths they touched are removed. That also
        happens when the provider call raises something that leaves the outcome
        unknown (ProviderError or an unexpected exception), because the remote
        file may have changed before the error reached us. When delete or move
        gets not_found, the entry for the missing source path is removed too,
        because not_found proves the cached metadata is stale. It does not
        happen when the provider cleanly refuses the call (bad input,
        conflict, permission), because nothing changed. The original error is
        always re-raised unchanged.

        Redis is only an optimisation. If Redis fails, or holds a value we
        can't read, the problem is logged and the call carries on with the
        wrapped storage, so callers never see it.
    """

    def __init__(
        self,
        storage: DocumentStorage,
        redis_client: redis.Redis,
        ttl_seconds: int,
    ):
        self.storage = storage
        self.redis = redis_client
        self.ttl_seconds = ttl_seconds

    def upload(
        self,
        path: str,
        content: bytes,
    ) -> FileResource:
        return self._mutate(
            [path],
            lambda: self.storage.upload(path, content),
        )

    def get_metadata(
        self,
        path: str,
    ) -> FileResource:
        cached, redis_ok = self._read(path)

        if cached is not None:
            return cached

        metadata = self.storage.get_metadata(path)

        # If Redis just failed, don't wait on it again for the write.
        if redis_ok:
            self._write(path, metadata)

        return metadata

    def download(
        self,
        path: str,
    ) -> bytes:
        # File contents are never cached.
        return self.storage.download(path)

    def move(
        self,
        path: str,
        new_path: str,
    ) -> FileResource:
        return self._mutate(
            [path, new_path],
            lambda: self.storage.move(path, new_path),
            # A move's not_found always means the source: the wrapped storage
            # reports a missing destination as a conflict or provider error,
            # never as not_found. So only the source entry is stale.
            not_found_paths=[path],
        )

    def delete(
        self,
        path: str,
    ) -> None:
        self._mutate(
            [path],
            lambda: self.storage.delete(path),
            not_found_paths=[path],
        )

    def _mutate(
        self,
        paths: list[str],
        call: Callable[[], T],
        not_found_paths: list[str] | None = None,
    ) -> T:
        """Run a changing call, then drop the cached entries it may have changed.

        not_found_paths are the entries to drop if the provider answers
        FileNotFoundError: that answer proves what we had cached for them is
        stale. Leave it out when not_found says nothing about a cached path.
        """
        try:
            result = call()
        except StorageError as exc:
            if isinstance(exc, ProviderError):
                # We don't know what the provider did.
                self._invalidate(*paths)
            elif isinstance(exc, FileNotFoundError) and not_found_paths:
                # The provider confirmed the file is gone, so the cached
                # metadata for it is stale.
                self._invalidate(*not_found_paths)
            # Every other StorageError is a clean refusal that changed nothing,
            # so the cache is still right.
            raise
        except Exception:
            # Anything unexpected also leaves the outcome unknown.
            self._invalidate(*paths)
            raise

        self._invalidate(*paths)
        return result

    def _read(self, path: str) -> tuple[FileResource | None, bool]:
        """Return (cached metadata or None, whether Redis answered)."""
        try:
            raw = self.redis.get(metadata_key(path))
        except RedisError as exc:
            self._log_error("read", exc)
            return None, False
        except ValueError as exc:
            # The client could not decode the stored bytes (UnicodeDecodeError).
            # Redis answered, the value is bad, so refill it from the provider.
            self._log_error("read", exc)
            return None, True

        if raw is None:
            logger.info("cache_miss key=%s", key_id(path))
            return None, True

        try:
            metadata = FileResource.model_validate_json(raw)
        except ValueError as exc:
            # A value we can't read is treated as a miss and overwritten.
            self._log_error("read", exc)
            return None, True

        logger.info("cache_hit key=%s", key_id(path))
        return metadata, True

    def _write(self, path: str, metadata: FileResource) -> None:
        try:
            self.redis.set(
                metadata_key(path),
                metadata.model_dump_json(),
                ex=self.ttl_seconds,
            )
        except RedisError as exc:
            self._log_error("write", exc)
            return

        logger.info(
            "cache_write key=%s ttl_seconds=%s", key_id(path), self.ttl_seconds
        )

    def _invalidate(self, *paths: str) -> None:
        try:
            self.redis.delete(*(metadata_key(path) for path in paths))
        except RedisError as exc:
            # The old entry may survive until its TTL runs out.
            self._log_error("invalidate", exc)
            return

        logger.info(
            "cache_invalidate keys=%s", ",".join(key_id(path) for path in paths)
        )

    def _log_error(self, operation: str, exc: Exception) -> None:
        # Only the exception type. The message can contain connection details.
        logger.warning(
            "cache_error operation=%s error=%s", operation, type(exc).__name__
        )
