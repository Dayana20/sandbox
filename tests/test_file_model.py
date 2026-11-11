from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.models.file import FileResource


def resource(modified_at):
    return FileResource(
        id="id:file",
        name="report.pdf",
        path="/docs/report.pdf",
        size=5,
        modified_at=modified_at,
        etag="015rev",
        type=None,
    )


def test_naive_dropbox_timestamp_is_interpreted_as_utc():
    value = resource(datetime(2026, 11, 4, 14, 30))

    assert value.modified_at == "2026-11-04T14:30:00Z"


def test_aware_timestamp_is_converted_to_utc_and_keeps_precision():
    value = resource(
        datetime(
            2026,
            11,
            4,
            9,
            30,
            0,
            123456,
            tzinfo=timezone(timedelta(hours=-5)),
        )
    )

    assert value.modified_at == "2026-11-04T14:30:00.123456Z"


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        ("2026-11-04T14:30:00Z", "2026-11-04T14:30:00Z"),
        ("2026-11-04T09:30:00-05:00", "2026-11-04T14:30:00Z"),
        ("2026-11-04T14:30:00", "2026-11-04T14:30:00Z"),
    ],
)
def test_string_timestamp_is_normalized(timestamp, expected):
    assert resource(timestamp).modified_at == expected


def test_invalid_timestamp_is_rejected():
    with pytest.raises(ValidationError):
        resource("not-a-timestamp")


def test_folder_metadata_supports_nullable_shared_fields():
    folder = FileResource(
        id="id:folder",
        name="docs",
        path="/docs",
        size=None,
        modified_at=None,
        etag=None,
        type=None,
    )

    assert folder.model_dump(mode="json") == {
        "id": "id:folder",
        "name": "docs",
        "path": "/docs",
        "size": None,
        "modified_at": None,
        "etag": None,
        "type": None,
    }


def test_provider_without_an_id_can_use_null():
    value = FileResource(
        id=None,
        name="report.pdf",
        path="/docs/report.pdf",
        size=5,
    )

    assert value.id is None
