from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from dropbox.exceptions import ApiError, RateLimitError
from dropbox.files import (
    DownloadError,
    LookupError,)

from app.errors import (
    FileNotFoundError,
    ProviderError,
)

from app.providers.dropbox.storage import DropboxStorage


def download_error(reason):
    # error = DownloadError.path(UploadWriteFailed(reason=reason, upload_session_id="1"))
    return ApiError("req", DownloadError.path(reason), None, None)

def test_dropbox_download_success():
    mock_client = Mock()
    # mocck client should have path and content attributes
    mock_client.files_download.return_value = (
        SimpleNamespace(
                id="id:abc123",
                name="test.pdf",
                path_display="/docs/test.pdf",
                size=11,
                server_modified="2026-10-05T12:00:00",
            ),
        SimpleNamespace(
            content=b"hello world"
        ),
    )
    storage = DropboxStorage(client=mock_client)

    result = storage.download("/docs/test.pdf")

    # mock_client.files_download.assert_called_once_with("/docs/test.pdf")
    assert isinstance(result, bytes)
    assert result == b"hello world"


def test_dropbox_download_file_not_found():
    mock_client = Mock()
    mock_client.not_found = True
    mock_client.files_download.side_effect = download_error(LookupError.not_found)
    storage = DropboxStorage(client=mock_client)

    # returns app.errors.FileNotFoundError: File not found: /docs/missing_file.pdf
    with pytest.raises(FileNotFoundError, match="File not found: /docs/missing_file.pdf"):
        storage.download("/docs/missing_file.pdf")


def test_dropbox_download_rate_limit_error():
    mock_client = Mock()
    mock_client.files_download.side_effect = RateLimitError("Too many requests")
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(ProviderError):
        storage.download("/docs/report.pdf")


def test_dropbox_download_unexpected_error():
    mock_client = Mock()
    api_error = Mock()
    api_error.is_path.return_value = False


    mock_client.files_download.side_effect = ApiError("req", api_error, None, None)
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(ProviderError):
        storage.download("/docs/report.pdf")


def test_dropbox_download_dropbox_exception():
    mock_client = Mock()
    mock_client.files_download.side_effect = Exception("Dropbox exception")
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(Exception):
        storage.download("/docs/report.pdf")
