from datetime import datetime
from unittest.mock import Mock

import pytest
from dropbox.exceptions import ApiError, RateLimitError
from dropbox.files import (
    FileMetadata,
    FolderMetadata,
    GetMetadataError,
    LookupError,
    UploadError,
    UploadWriteFailed,
    WriteConflictError,
    WriteError,
    WriteMode,
)

from app.errors import (
    FileConflictError,
    FileNotFoundError,
    InvalidRequestError,
    PermissionDeniedError,
    ProviderError,
)
from app.providers.dropbox.storage import DropboxStorage


REV = "015f9a1b2c3d4e5f60000000a"


def file_client():
    mock_client = Mock()
    current = Mock(spec=FileMetadata)
    current.rev = REV
    mock_client.files_get_metadata.return_value = current
    return mock_client


def upload_error(reason):
    return ApiError(
        "req", UploadError.path(UploadWriteFailed(reason=reason, upload_session_id="")), None, None
    )


def test_dropbox_replace_success():
    mock_client = file_client()
    mock_client.files_upload.return_value = FileMetadata(
        id="id:abc",
        name="report.pdf",
        path_display="/docs/report.pdf",
        size=12,
        server_modified=datetime(2026, 11, 3, 14, 30),
    )
    storage = DropboxStorage(client=mock_client)

    result = storage.replace("/docs/report.pdf", b"new contents")

    mock_client.files_get_metadata.assert_called_once_with("/docs/report.pdf")
    mock_client.files_upload.assert_called_once_with(
        b"new contents",
        "/docs/report.pdf",
        mode=WriteMode.update(REV),
        autorename=False,
        mute=True,
        strict_conflict=True,
    )
    assert result.id == "id:abc"
    assert result.size == 12


def test_dropbox_replace_missing_file_never_uploads():
    mock_client = Mock()
    mock_client.files_get_metadata.side_effect = ApiError(
        "req", GetMetadataError.path(LookupError.not_found), None, None
    )
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(FileNotFoundError):
        storage.replace("/missing.pdf", b"x")

    mock_client.files_upload.assert_not_called()


def test_dropbox_replace_refuses_folder():
    mock_client = Mock()
    mock_client.files_get_metadata.return_value = Mock(spec=FolderMetadata)
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(InvalidRequestError):
        storage.replace("/docs", b"x")

    mock_client.files_upload.assert_not_called()


def test_dropbox_replace_stale_rev_is_a_conflict():
    mock_client = file_client()
    mock_client.files_upload.side_effect = upload_error(
        WriteError.conflict(WriteConflictError.file)
    )
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(FileConflictError, match="changed while it was being replaced"):
        storage.replace("/report.pdf", b"x")


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (WriteError.no_write_permission, PermissionDeniedError),
        (WriteError.disallowed_name, InvalidRequestError),
        (WriteError.insufficient_space, ProviderError),
    ],
)
def test_dropbox_replace_write_errors(reason, expected):
    mock_client = file_client()
    mock_client.files_upload.side_effect = upload_error(reason)
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(expected):
        storage.replace("/report.pdf", b"x")


def test_dropbox_replace_rate_limited():
    mock_client = file_client()
    mock_client.files_upload.side_effect = RateLimitError("req", None, 1)
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(ProviderError):
        storage.replace("/report.pdf", b"x")
