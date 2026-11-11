from unittest.mock import Mock

import pytest
from dropbox.exceptions import ApiError, RateLimitError
from dropbox.files import (
    DeleteError,
    LookupError,
    WriteError,
)
from requests.exceptions import ConnectionError as RequestsConnectionError

from app.errors import (
    FileNotFoundError,
    PermissionDeniedError,
    ProviderError,
)
from app.providers.dropbox.storage import DropboxStorage


def test_dropbox_delete_file():
    mock_client = Mock()
    storage = DropboxStorage(client=mock_client)

    result = storage.delete("/docs/report.pdf")

    mock_client.files_delete_v2.assert_called_once_with("/docs/report.pdf")
    assert result is None


def test_dropbox_delete_folder_is_one_call():
    # files_delete_v2 removes a folder with everything in it, so a folder
    # needs no metadata check and no listing first.
    mock_client = Mock()
    storage = DropboxStorage(client=mock_client)

    storage.delete("/docs")

    mock_client.files_delete_v2.assert_called_once_with("/docs")
    mock_client.files_get_metadata.assert_not_called()
    mock_client.files_list_folder.assert_not_called()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (DeleteError.path_lookup(LookupError.not_found), FileNotFoundError),
        (DeleteError.path_write(WriteError.no_write_permission), PermissionDeniedError),
        (DeleteError.too_many_write_operations, ProviderError),
        (DeleteError.too_many_files, ProviderError),
    ],
)
def test_dropbox_delete_errors(error, expected):
    mock_client = Mock()
    mock_client.files_delete_v2.side_effect = ApiError("req", error, None, None)
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(expected):
        storage.delete("/report.pdf")


def test_dropbox_delete_rate_limited():
    mock_client = Mock()
    mock_client.files_delete_v2.side_effect = RateLimitError("req", None, 1)
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(ProviderError):
        storage.delete("/report.pdf")


def test_dropbox_delete_network_failure_is_a_provider_error():
    # The request may have reached Dropbox, so the outcome is unknown.
    mock_client = Mock()
    mock_client.files_delete_v2.side_effect = RequestsConnectionError("reset")
    storage = DropboxStorage(client=mock_client)

    with pytest.raises(ProviderError):
        storage.delete("/report.pdf")
