from unittest.mock import Mock, patch
from app.providers.dropbox.storage import DropboxStorage
from types import SimpleNamespace



def test_get_dropbox_metadata_success():
    path = "/test.paper"
    mock_metadata_success_response = SimpleNamespace(
        id="id:vx1IJ3ku3qwAAAAAAAAACQ",
        name="test.paper",
        path_display="/test.paper",
        size=200,
        server_modified="2026-10-04T22:01:41"
    )

    mock_client = Mock()
    mock_client.files_get_metadata.return_value = mock_metadata_success_response
    storage = DropboxStorage(client=mock_client)
    result = storage.get_metadata(path)

    assert result.name == "test.paper"
    assert result.size == 200
    mock_client.files_get_metadata.assert_called_once_with(path)
