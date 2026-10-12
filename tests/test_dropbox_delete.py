from unittest.mock import Mock

import pytest
from dropbox.exceptions import ApiError, RateLimitError
from dropbox.files import (
    DeleteError,
    FileMetadata,
    FolderMetadata,
    GetMetadataError,
    LookupError,
    WriteError,
)

from app.errors import (
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


def test_dropbox_delete_success():
    mock_client = file_client()
    storage = DropboxStorage(client=mock_client)

    result = storage.delete("/docs/report.pdf")

    mock_client.files_delete_v2.assert_called_once_with("/docs/report.pdf")
    assert result is None


def test_dropbox_delete_refuses_folder():
    mock_client = Mock()
    mock_client.files_get_metadata.return_value = Mock(spec=FolderMetadata)
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(InvalidRequestError):
        storage.delete("/docs")

    mock_client.files_delete_v2.assert_not_called()


def test_dropbox_delete_missing_file():
    mock_client = Mock()
    mock_client.files_get_metadata.side_effect = ApiError(
        "req", GetMetadataError.path(LookupError.not_found), None, None
    )
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(FileNotFoundError):
        storage.delete("/report.pdf")

    mock_client.files_delete_v2.assert_not_called()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (DeleteError.path_lookup(LookupError.not_found), FileNotFoundError),
        (DeleteError.path_write(WriteError.no_write_permission), PermissionDeniedError),
        (DeleteError.too_many_write_operations, ProviderError),
    ],
)
def test_dropbox_delete_errors(error, expected):
    mock_client = file_client()
    mock_client.files_delete_v2.side_effect = ApiError("req", error, None, None)
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(expected):
        storage.delete("/report.pdf")


def test_dropbox_delete_rate_limited():
    mock_client = Mock()
    mock_client.files_get_metadata.side_effect = RateLimitError("req", None, 1)
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(ProviderError):
        storage.delete("/report.pdf")
