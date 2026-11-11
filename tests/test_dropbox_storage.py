from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from dropbox.exceptions import ApiError, InternalServerError, RateLimitError
from dropbox.files import (
    DeletedMetadata,
    FileMetadata,
    FolderMetadata,
    GetMetadataError,
    LookupError,
)
import requests

from app.errors import (
    FileNotFoundError,
    InvalidRequestError,
    PermissionDeniedError,
    ProviderError,
    ProviderUnavailableError,
)
from app.providers.dropbox.storage import DropboxStorage


def file_metadata():
    metadata = Mock(spec=FileMetadata)
    metadata.id = "id:vx1IJ3ku3qwAAAAAAAAACQ"
    metadata.name = "test.paper"
    metadata.path_display = "/test.paper"
    metadata.size = 200
    metadata.server_modified = datetime(2026, 10, 4, 22, 1, 41)
    metadata.rev = "015rev"
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
    assert result.modified_at == "2026-10-04T22:01:41Z"
    assert result.etag == "015rev"
    assert result.type is None


def test_get_dropbox_folder_metadata_success():
    mock_client = Mock()
    folder = Mock(spec=FolderMetadata)
    folder.id = "id:folder"
    folder.name = "docs"
    folder.path_display = "/docs"
    mock_client.files_get_metadata.return_value = folder
    storage = DropboxStorage(client=mock_client)

    result = storage.get_metadata("/docs")

    assert result.id == "id:folder"
    assert result.name == "docs"
    assert result.path == "/docs"
    assert result.modified_at is None
    assert result.etag is None
    assert result.type is None


def test_get_dropbox_deleted_metadata_is_not_returned_as_live():
    mock_client = Mock()
    deleted = Mock(spec=DeletedMetadata)
    mock_client.files_get_metadata.return_value = deleted
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(FileNotFoundError):
        storage.get_metadata("/deleted.pdf")


def test_get_dropbox_metadata_converts_aware_timestamp_to_utc():
    mock_client = Mock()
    metadata = file_metadata()
    metadata.server_modified = datetime(
        2026,
        10,
        4,
        18,
        1,
        41,
        123456,
        tzinfo=timezone(timedelta(hours=-4)),
    )
    mock_client.files_get_metadata.return_value = metadata

    result = DropboxStorage(client=mock_client).get_metadata("/test.paper")

    assert result.modified_at == "2026-10-04T22:01:41.123456Z"


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


def test_get_dropbox_metadata_internal_error_is_unavailable():
    mock_client = Mock()
    mock_client.files_get_metadata.side_effect = InternalServerError(
        "req", 503, "provider body"
    )
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(ProviderUnavailableError):
        storage.get_metadata("/report.pdf")

# make a mocked files_get_metadata raise requests.exceptions.ReadTimeout
# mock should raise requests.exceptions.ReadTimeout
def test_get_dropbox_metadata_request_exception():
    mock_client = Mock()
    mock_client.files_get_metadata.side_effect = requests.exceptions.ReadTimeout("Request timed out")
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(ProviderUnavailableError):
        storage.get_metadata("/report.pdf")

# assert DropboxStorage.get_metadata() raises the  ProviderError
# mock should return requests.exceptions.ConnectionError
def test_get_dropbox_metadata_dropbox_exception():
    mock_client = Mock()
    mock_client.files_get_metadata.side_effect = requests.exceptions.ConnectionError("Connection error")
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(ProviderError):
        storage.get_metadata("/report.pdf")
