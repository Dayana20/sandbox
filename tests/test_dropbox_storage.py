from datetime import datetime
from unittest.mock import Mock

import pytest
from dropbox.exceptions import ApiError, RateLimitError
from dropbox.files import FileMetadata, FolderMetadata, GetMetadataError, LookupError

from app.errors import (
    FileNotFoundError,
    InvalidRequestError,
    PermissionDeniedError,
    ProviderError,
)
from app.providers.dropbox.storage import DropboxStorage


def file_metadata():
    metadata = Mock(spec=FileMetadata)
    metadata.id = "id:vx1IJ3ku3qwAAAAAAAAACQ"
    metadata.name = "test.paper"
    metadata.path_display = "/test.paper"
    metadata.size = 200
    metadata.server_modified = datetime(2026, 10, 4, 22, 1, 41)
    return metadata


def lookup_error(error):
    return ApiError("req", GetMetadataError.path(error), None, None)


def test_get_dropbox_metadata_success():
    mock_client = Mock()
    mock_client.files_get_metadata.return_value = file_metadata()
    storage = DropboxStorage(client=mock_client)

    result = storage.get_metadata("/test.paper")

    mock_client.files_get_metadata.assert_called_once_with("/test.paper")
    assert result.id == "id:vx1IJ3ku3qwAAAAAAAAACQ"
    assert result.name == "test.paper"
    assert result.path == "/test.paper"
    assert result.size == 200


def test_get_dropbox_metadata_refuses_folder():
    mock_client = Mock()
    mock_client.files_get_metadata.return_value = Mock(spec=FolderMetadata)
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(InvalidRequestError):
        storage.get_metadata("/docs")


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (LookupError.not_found, FileNotFoundError),
        (LookupError.malformed_path("bad"), InvalidRequestError),
        (LookupError.restricted_content, PermissionDeniedError),
    ],
)
def test_get_dropbox_metadata_lookup_errors(error, expected):
    mock_client = Mock()
    mock_client.files_get_metadata.side_effect = lookup_error(error)
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(expected):
        storage.get_metadata("/report.pdf")


def test_get_dropbox_metadata_rate_limited():
    mock_client = Mock()
    mock_client.files_get_metadata.side_effect = RateLimitError("req", None, 1)
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(ProviderError):
        storage.get_metadata("/report.pdf")
