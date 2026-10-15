from datetime import datetime
from unittest.mock import Mock

import pytest
from dropbox.exceptions import ApiError, RateLimitError
from dropbox.files import (
    FileMetadata,
    FolderMetadata,
    GetMetadataError,
    LookupError,
    RelocationError,
    RelocationResult,
    WriteConflictError,
    WriteError,
)

from app.errors import (
    FileConflictError,
    FileNotFoundError,
    InvalidRequestError,
    PermissionDeniedError,
    ProviderError,
)
from app.providers.dropbox.storage import DropboxStorage


def file_client():
    mock_client = Mock()
    mock_client.files_get_metadata.return_value = Mock(spec=FileMetadata)
    return mock_client


def test_dropbox_move_success():
    mock_client = file_client()
    mock_client.files_move_v2.return_value = RelocationResult(
        metadata=FileMetadata(
            id="id:abc",
            name="final.pdf",
            path_display="/archive/final.pdf",
            size=5,
            server_modified=datetime(2026, 10, 5, 14, 30),
        )
    )
    storage = DropboxStorage(client=mock_client)

    result = storage.move("/docs/report.pdf", "/archive/final.pdf")

    mock_client.files_move_v2.assert_called_once_with(
        "/docs/report.pdf", "/archive/final.pdf", autorename=False
    )
    assert result.id == "id:abc"
    assert result.name == "final.pdf"
    assert result.path == "/archive/final.pdf"
    assert result.size == 5


def test_dropbox_move_refuses_folder():
    mock_client = Mock()
    mock_client.files_get_metadata.return_value = Mock(spec=FolderMetadata)
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(InvalidRequestError):
        storage.move("/docs", "/archive")

    mock_client.files_move_v2.assert_not_called()


def test_dropbox_move_missing_file():
    mock_client = Mock()
    mock_client.files_get_metadata.side_effect = ApiError(
        "req", GetMetadataError.path(LookupError.not_found), None, None
    )
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(FileNotFoundError):
        storage.move("/missing.pdf", "/renamed.pdf")

    mock_client.files_move_v2.assert_not_called()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RelocationError.from_lookup(LookupError.not_found), FileNotFoundError),
        (RelocationError.from_write(WriteError.no_write_permission), PermissionDeniedError),
        (RelocationError.to(WriteError.conflict(WriteConflictError.file)), FileConflictError),
        (RelocationError.to(WriteError.no_write_permission), PermissionDeniedError),
        (RelocationError.to(WriteError.disallowed_name), InvalidRequestError),
        (RelocationError.insufficient_quota, ProviderError),
    ],
)
def test_dropbox_move_errors(error, expected):
    mock_client = file_client()
    mock_client.files_move_v2.side_effect = ApiError("req", error, None, None)
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(expected):
        storage.move("/report.pdf", "/renamed.pdf")


def test_dropbox_move_conflict_names_destination():
    mock_client = file_client()
    mock_client.files_move_v2.side_effect = ApiError(
        "req", RelocationError.to(WriteError.conflict(WriteConflictError.file)), None, None
    )
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(FileConflictError, match="/renamed.pdf"):
        storage.move("/report.pdf", "/renamed.pdf")


def test_dropbox_move_rate_limited():
    mock_client = file_client()
    mock_client.files_move_v2.side_effect = RateLimitError("req", None, 1)
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(ProviderError):
        storage.move("/report.pdf", "/renamed.pdf")
