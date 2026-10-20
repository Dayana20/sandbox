import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import redis
from redis.exceptions import RedisError

from app.errors import IdempotencyUnavailableError

logger = logging.getLogger(__name__)

# One scope for the whole service: the same Idempotency-Key means the same
# logical upload, whoever sends it. The caller's key is hashed before it
# gets here, so it never appears in Redis.
KEY_PREFIX = "document-storage:idempotency:upload:"

IN_PROGRESS = "in_progress"
SUCCEEDED = "succeeded"
UNCERTAIN = "uncertain"
STATES = (IN_PROGRESS, SUCCEEDED, UNCERTAIN)

# How often reserve() retries when the record vanishes between the failed
# claim and the read (it expired or was released at that exact moment).
RESERVE_ATTEMPTS = 3

# Results of the two scripts below.
APPLIED = 1
RECORD_MISSING = 0
OWNER_CHANGED = -1

# Both scripts run inside Redis, so the owner check and the change are one
# atomic step. Nothing can touch the record between them.
#
# KEYS[1] the record. ARGV[1] the owner we expect.
# They return APPLIED, RECORD_MISSING, or OWNER_CHANGED (the record belongs to
# another reservation, or is unreadable, so it is not ours to touch).
_REPLACE_IF_OWNER = """
local raw = redis.call("GET", KEYS[1])
if not raw then return 0 end
local ok, record = pcall(cjson.decode, raw)
if not ok or type(record) ~= "table" or record["owner"] ~= ARGV[1] then
    return -1
end
redis.call("SET", KEYS[1], ARGV[2], "EX", tonumber(ARGV[3]))
return 1
"""  # ARGV[2] the new record, ARGV[3] its TTL in seconds

_DELETE_IF_OWNER = """
local raw = redis.call("GET", KEYS[1])
if not raw then return 0 end
local ok, record = pcall(cjson.decode, raw)
if not ok or type(record) ~= "table" or record["owner"] ~= ARGV[1] then
    return -1
end
redis.call("DEL", KEYS[1])
return 1
"""


def redis_key(key_hash: str) -> str:
    return f"{KEY_PREFIX}{key_hash}"


@dataclass(frozen=True)
class IdempotencyRecord:
    """
        What another request sees when it finds a key already in use.

        The owner token is deliberately not part of this. Only the request
        that claimed the key ever holds it.
    """

    state: str
    fingerprint: str
    response: dict[str, Any] | None = None


class RedisIdempotencyStore:
    """
        Keeps one record per idempotency key in Redis.

        Unlike a cache, this must be correct: when Redis fails, every method
        raises IdempotencyUnavailableError so the caller can refuse the
        request instead of uploading without protection. Redis messages are
        logged by exception type only and never reach the caller.

        Each claim gets a random owner token, stored in the record. Changing
        or deleting the record afterwards needs that token, so a request whose
        record expired can never touch a newer reservation of the same key.
    """

    def __init__(self, client: redis.Redis | None, ttl_seconds: int):
        self.client = client
        self.ttl_seconds = ttl_seconds
        self._replace_script = (
            client.register_script(_REPLACE_IF_OWNER) if client is not None else None
        )
        self._delete_script = (
            client.register_script(_DELETE_IF_OWNER) if client is not None else None
        )

    def reserve(
        self,
        key_hash: str,
        fingerprint: str,
    ) -> str | IdempotencyRecord:
        """
            Claim the key before the provider is called.

            Returns the owner token if this call claimed it. Keep it: it is
            needed for every later change to the record. Otherwise returns the
            record that is already there, with no ownership. The claim is a
            single SET ... NX, so two overlapping requests can never both
            claim the same key.
        """
        client = self._client(key_hash)
        owner = uuid.uuid4().hex
        claim = _encode(IN_PROGRESS, fingerprint, owner)

        for _ in range(RESERVE_ATTEMPTS):
            try:
                if client.set(redis_key(key_hash), claim, nx=True, ex=self.ttl_seconds):
                    return owner
                raw = client.get(redis_key(key_hash))
            except (RedisError, ValueError) as exc:
                raise self._unavailable(key_hash, "reserve", exc) from exc

            if raw is not None:
                return self._parse(key_hash, raw)

        raise self._unavailable(key_hash, "reserve", RuntimeError("record keeps vanishing"))

    def save_succeeded(
        self,
        key_hash: str,
        owner: str,
        fingerprint: str,
        response: dict[str, Any],
    ) -> bool:
        """
            Store the successful result, if the record is still ours.

            Returns False, and changes nothing, if the record is gone or now
            belongs to another reservation.
        """
        return self._replace_if_owner(
            key_hash,
            owner,
            "save_succeeded",
            SUCCEEDED,
            _encode(SUCCEEDED, fingerprint, owner, response),
        )

    def mark_uncertain(self, key_hash: str, owner: str, fingerprint: str) -> bool:
        """
            Keep the key blocked: the provider may have done the upload.

            Only changes the record if it is still ours. Returns whether it did.
        """
        return self._replace_if_owner(
            key_hash,
            owner,
            "mark_uncertain",
            UNCERTAIN,
            _encode(UNCERTAIN, fingerprint, owner),
        )

    def release(self, key_hash: str, owner: str) -> bool:
        """
            Forget the key. Only for failures that prove nothing was uploaded.

            Only deletes the record if it is still ours. Returns whether it did.
        """
        self._client(key_hash)
        script = self._delete_script
        if script is None:
            raise self._unavailable(key_hash, "release", RuntimeError("no script"))

        return self._run(
            key_hash,
            "release",
            f"{IN_PROGRESS}->released",
            lambda: script(keys=[redis_key(key_hash)], args=[owner]),
        )

    def _replace_if_owner(
        self,
        key_hash: str,
        owner: str,
        operation: str,
        new_state: str,
        new_record: str,
    ) -> bool:
        self._client(key_hash)
        script = self._replace_script
        if script is None:
            raise self._unavailable(key_hash, operation, RuntimeError("no script"))

        return self._run(
            key_hash,
            operation,
            f"{IN_PROGRESS}->{new_state}",
            lambda: script(
                keys=[redis_key(key_hash)],
                args=[owner, new_record, self.ttl_seconds],
            ),
        )

    def _run(self, key_hash: str, operation: str, transition: str, call: Any) -> bool:
        try:
            result = int(call())
        except (RedisError, ValueError, TypeError) as exc:
            raise self._unavailable(key_hash, operation, exc) from exc

        if result == APPLIED:
            return True

        # Not ours any more (expired, or a newer request claimed the key).
        # Leave the record exactly as it is. The owner token and fingerprint
        # are not logged.
        logger.warning(
            "idempotency_state_update_skipped operation=%s transition=%s reason=%s key_id=%s",
            operation,
            transition,
            "record_missing" if result == RECORD_MISSING else "owner_changed",
            key_hash[:12],
        )

        return False

    def _client(self, key_hash: str) -> redis.Redis:
        if self.client is None:
            raise self._unavailable(
                key_hash,
                "connect",
                RuntimeError("REDIS_URL is not set"),
            )

        return self.client

    def _parse(self, key_hash: str, raw: str | bytes) -> IdempotencyRecord:
        try:
            data = json.loads(raw)
            state = data["state"]
            fingerprint = data["fingerprint"]
            response = data.get("response")

            if state not in STATES or not isinstance(fingerprint, str):
                raise ValueError("unexpected record")
            if state == SUCCEEDED and not isinstance(response, dict):
                raise ValueError("succeeded record without a response")
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            # We can't tell what happened to this key, so don't guess.
            raise self._unavailable(key_hash, "read", exc) from exc

        return IdempotencyRecord(state, fingerprint, response)

    def _unavailable(
        self,
        key_hash: str,
        operation: str,
        exc: BaseException,
    ) -> IdempotencyUnavailableError:
        logger.error(
            "idempotency_error operation=%s key_id=%s error=%s",
            operation,
            key_hash[:12],
            type(exc).__name__,
        )

        return IdempotencyUnavailableError()


def _encode(
    state: str,
    fingerprint: str,
    owner: str,
    response: dict[str, Any] | None = None,
) -> str:
    record: dict[str, Any] = {
        "state": state,
        "fingerprint": fingerprint,
        "owner": owner,
    }
    if response is not None:
        record["response"] = response

    return json.dumps(record)
