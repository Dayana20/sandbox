from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from dropbox.exceptions import ApiError, RateLimitError
from dropbox.files import (
    UploadError,
    UploadWriteFailed,
    WriteConflictError,
    WriteError,
    WriteMode,
)

from app.errors import (
    FileConflictError,
    InvalidRequestError,
    PermissionDeniedError,
    ProviderError,
)
from app.providers.dropbox.storage import DropboxStorage


def upload_error(reason):
    error = UploadError.path(UploadWriteFailed(reason=reason, upload_session_id="1"))
    return ApiError("req", error, None, None)


def test_dropbox_upload_success():
    mock_client = Mock()
    mock_client.files_upload.return_value = SimpleNamespace(
        id="id:abc123",
        name="report.pdf",
        path_display="/docs/report.pdf",
        size=5,
        server_modified="2026-10-05T12:00:00",
    )
    storage = DropboxStorage(client=mock_client)

    result = storage.upload("/docs/report.pdf", b"hello")

    mock_client.files_upload.assert_called_once_with(
        b"hello",
        "/docs/report.pdf",
        mode=WriteMode.add,
        autorename=False,
        mute=True,
        strict_conflict=True,
    )
    assert result.id == "id:abc123"
    assert result.name == "report.pdf"
    assert result.size == 5


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (WriteError.conflict(WriteConflictError.file), FileConflictError),
        (WriteError.no_write_permission, PermissionDeniedError),
        (WriteError.disallowed_name, InvalidRequestError),
        (WriteError.insufficient_space, ProviderError),
    ],
)
def test_dropbox_upload_errors(reason, expected):
    mock_client = Mock()
    mock_client.files_upload.side_effect = upload_error(reason)
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(expected):
        storage.upload("/report.pdf", b"hello")


def test_dropbox_upload_rate_limited():
    mock_client = Mock()
    mock_client.files_upload.side_effect = RateLimitError("req", None, 1)
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(ProviderError):
        storage.upload("/report.pdf", b"hello")
