"""Data model shared by every Document Storage service in Team 1/3/6."""

from dataclasses import dataclass


@dataclass
class FileInfo:
    """Describes a file or folder, as returned by create, replace, metadata, move and list.

    Attributes:
        id: ID, or None when the provider has none (S3).
        name: Last path segment, for example ``report.pdf``.
        path: Absolute path with a leading slash, for example ``/docs/report.pdf``.
        size: Size in bytes, or None for folders.
        modified_at: ISO 8601 UTC timestamp ending in ``Z``, or None for folders.
        etag: Fingerprint that changes on change
        type: ``"file"`` or ``"folder"``. Set on list entries only.

    """

    id: str | None
    name: str
    path: str
    size: int | None
    modified_at: str | None
    etag: str | None
    type: str | None
