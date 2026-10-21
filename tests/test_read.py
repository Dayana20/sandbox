import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_document_storage
from app.errors import InvalidRequestError, PermissionDeniedError, ProviderError
from app.main import app
from tests.fakes import FakeDocumentStorage

from app.providers.dropbox.storage import DropboxStorage
from requests.exceptions import ReadTimeout
from unittest.mock import Mock


client = TestClient(app)


@pytest.fixture
def storage():
    fake_storage = FakeDocumentStorage()
    app.dependency_overrides[get_document_storage] = lambda: fake_storage
    yield fake_storage
    app.dependency_overrides.clear()


def get_metadata(path=None):
    params = {}

    if path is not None:
        params["path"] = path

    return client.get("/files/metadata", params=params)


def test_get_metadata(storage):
    storage.upload("/docs/report.pdf", b"hello")

    response = get_metadata("/docs/report.pdf")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "report.pdf"
    assert body["path"] == "/docs/report.pdf"
    assert body["size"] == 5


def test_get_metadata_missing_file(storage):
    response = get_metadata("/missing.pdf")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_get_metadata_without_path(storage):
    response = get_metadata()

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


@pytest.mark.parametrize("path", ["", "report.pdf", "/docs/", "/docs/../report.pdf"])
def test_get_metadata_bad_path(storage, path):
    response = get_metadata(path)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_get_metadata_does_not_change_storage(storage):
    storage.upload("/report.pdf", b"hello")

    get_metadata("/report.pdf")

    assert storage.download("/report.pdf") == b"hello"


class FailingStorage(FakeDocumentStorage):

    def __init__(self, error):
        super().__init__()
        self.error = error

    def get_metadata(self, path):
        raise self.error


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (InvalidRequestError("Only files have metadata"), 400, "invalid_request"),
        (PermissionDeniedError("No permission"), 403, "permission_denied"),
        (ProviderError("Dropbox is down"), 502, "provider_error"),
    ],
)
def test_get_metadata_storage_errors(error, status, code):
    app.dependency_overrides[get_document_storage] = lambda: FailingStorage(error)

    response = get_metadata("/report.pdf")
    app.dependency_overrides.clear()

    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_get_metadata_dropbox_timeout():
    mock_client = Mock()
    mock_client.files_get_metadata.side_effect = ReadTimeout("Request timed out")
    storage = DropboxStorage(client=mock_client)

    app.dependency_overrides[get_document_storage] = lambda: storage

    response = get_metadata("/report.pdf")
    app.dependency_overrides.clear()

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "provider_error"