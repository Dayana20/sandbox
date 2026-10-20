import hashlib
import json
import logging
from collections.abc import Callable
from typing import Protocol

from app.errors import (
    FileConflictError,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyOutcomeUnknownError,
    IdempotencyUnavailableError,
    InvalidRequestError,
    PermissionDeniedError,
)
from app.idempotency.redis_store import (
    IN_PROGRESS,
    SUCCEEDED,
    UNCERTAIN,
    IdempotencyRecord,
)
from app.models.file import FileResource

logger = logging.getLogger(__name__)

MAX_KEY_LENGTH = 255

# Upload failures that prove the provider did not create the file. Each one
# is an answer Dropbox gave to this request, so nothing was written:
#   InvalidRequestError   Dropbox refused the path or name (or the input)
#   PermissionDeniedError Dropbox refused the credentials or write access
#   FileConflictError     a file is already at the path (strict_conflict, no
#                         overwrite, no rename)
# For these the record is released, so the caller can fix the input and use
# the same key again. Every other failure, ProviderError included, is
# treated as "outcome unknown".
DEFINITIVE_FAILURES = (
    InvalidRequestError,
    PermissionDeniedError,
    FileConflictError,
)


class IdempotencyStore(Protocol):
    # reserve returns the owner token when this request claimed the key, or
    # the existing record when someone else holds it. The other methods
    # change the record only while it still belongs to that owner, and
    # return whether they did.
    def reserve(self, key_hash: str, fingerprint: str) -> str | IdempotencyRecord: ...

    def save_succeeded(
        self, key_hash: str, owner: str, fingerprint: str, response: dict
    ) -> bool: ...

    def mark_uncertain(self, key_hash: str, owner: str, fingerprint: str) -> bool: ...

    def release(self, key_hash: str, owner: str) -> bool: ...


def validate_idempotency_key(key: str) -> str:
    """
        Check a caller-supplied Idempotency-Key. Same 400 as other bad input.

        Raises:
            InvalidRequestError: If it is empty or longer than 255 characters.
    """
    if not 1 <= len(key) <= MAX_KEY_LENGTH:
        raise InvalidRequestError(
            f"Idempotency-Key must be 1 to {MAX_KEY_LENGTH} characters"
        )

    return key


def hash_key(key: str) -> str:
    """SHA-256 of the caller's key. This is what Redis and the logs see."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def upload_fingerprint(path: str, content: bytes) -> str:
    """
        Identify one logical upload request.

        It covers everything that changes what the upload does: the
        destination path and the file bytes (as their SHA-256, so the file is
        never stored). The file name and content type the caller sends are
        left out because the upload ignores them. The fields go through
        canonical JSON, so no two different requests can serialize the same.
    """
    document = {
        "operation": "upload",
        "version": 1,
        "path": path,
        "content_sha256": hashlib.sha256(content).hexdigest(),
    }
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class IdempotencyService:
    """
        Makes an upload run at most once per Idempotency-Key.

        It sits between the route and DocumentStorage. The provider does not
        know about it. The first request claims the key, uploads, and stores
        the result. Later requests with the same key and the same
        fingerprint get the stored result, or an error that says why the
        upload was not run again. The upload is never started a second time
        for a key whose first attempt may have reached the provider.

        If the store fails, IdempotencyUnavailableError is raised before the
        provider is called. There is no fail-open path.
    """

    def __init__(self, store: IdempotencyStore):
        self.store = store

    def run_upload(
        self,
        key: str,
        fingerprint: str,
        upload: Callable[[], FileResource],
    ) -> FileResource:
        key_hash = hash_key(key)
        key_id = key_hash[:12]

        claimed = self.store.reserve(key_hash, fingerprint)

        if isinstance(claimed, IdempotencyRecord):
            # Someone else holds the key. We own nothing and change nothing.
            return self._answer(claimed, fingerprint, key_id)

        logger.info("idempotency_reserved key_id=%s", key_id)
        return self._execute(key_hash, key_id, claimed, fingerprint, upload)

    def _execute(
        self,
        key_hash: str,
        key_id: str,
        owner: str,
        fingerprint: str,
        upload: Callable[[], FileResource],
    ) -> FileResource:
        # Every change below passes `owner`, so it only lands if the record
        # is still the one this request claimed. If the record expired and a
        # newer request claimed the key, the store skips the change and logs
        # idempotency_state_update_skipped. The caller still gets the
        # original result or error either way.
        try:
            resource = upload()
        except DEFINITIVE_FAILURES:
            if self._best_effort(self.store.release, key_hash, owner):
                logger.info("idempotency_released key_id=%s", key_id)
            raise
        except Exception:
            # The provider may have created the file. Keep the key blocked.
            logger.warning(
                "idempotency_uncertain key_id=%s action=marked", key_id
            )
            self._best_effort(self.store.mark_uncertain, key_hash, owner, fingerprint)
            raise

        # The upload happened, so the caller gets the result even if saving
        # it fails. The record then stays in_progress and blocks the key
        # until it expires, which is the safe side.
        self._best_effort(
            self.store.save_succeeded,
            key_hash,
            owner,
            fingerprint,
            resource.model_dump(mode="json"),
        )

        return resource

    def _answer(
        self,
        existing: IdempotencyRecord,
        fingerprint: str,
        key_id: str,
    ) -> FileResource:
        if existing.fingerprint != fingerprint:
            logger.warning("idempotency_conflict key_id=%s", key_id)
            raise IdempotencyConflictError()

        if existing.state == SUCCEEDED and existing.response is not None:
            logger.info("idempotency_replay key_id=%s", key_id)
            return FileResource.model_validate(existing.response)

        if existing.state == UNCERTAIN:
            logger.warning("idempotency_uncertain key_id=%s action=blocked", key_id)
            raise IdempotencyOutcomeUnknownError()

        if existing.state == IN_PROGRESS:
            logger.info("idempotency_in_progress key_id=%s", key_id)
            raise IdempotencyInProgressError()

        # The store only returns the three states above.
        raise IdempotencyUnavailableError()

    @staticmethod
    def _best_effort(action: Callable[..., bool | None], *args: object) -> bool | None:
        """
            Run a bookkeeping step after the provider was already called.

            A Redis failure here must not replace the provider's result or
            error, so it is only logged (the store already did that).
        """
        try:
            return action(*args)
        except IdempotencyUnavailableError:
            return None
