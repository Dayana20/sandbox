from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, field_validator


def format_utc_timestamp(value: datetime | str | None) -> str | None:
    """Normalize a provider/cache timestamp to ISO 8601 UTC ending in ``Z``."""
    if value is None:
        return None

    if isinstance(value, datetime):
        timestamp = value
    else:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            timestamp = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError("modified_at must be an ISO 8601 timestamp") from exc

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)

    return timestamp.isoformat().replace("+00:00", "Z")


class FileResource(BaseModel):
    """Provider-neutral resource metadata returned by file endpoints.

    ``modified_at`` is kept as the shared contract's wire type rather than a
    Python ``datetime`` so cache entries, idempotency replays and HTTP
    responses all use the same representation.
    """

    id: str | None
    name: str
    path: str
    size: int | None
    modified_at: str | None = None
    etag: str | None = None
    type: str | None = None

    @field_validator("modified_at", mode="before")
    @classmethod
    def normalize_modified_at(cls, value: Any) -> str | None:
        """Return an ISO 8601 UTC timestamp ending in ``Z``.

        Dropbox documents ``server_modified`` as UTC but supplies a naive
        ``datetime``. Treat that specific provider value (and legacy cached
        values produced from it) as UTC instead of interpreting it in the
        host machine's local timezone.
        """
        if value is None:
            return None

        if not isinstance(value, (datetime, str)):
            raise ValueError("modified_at must be an ISO 8601 timestamp")

        return format_utc_timestamp(value)
