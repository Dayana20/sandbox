import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_document_storage
from app.errors import PermissionDeniedError, ProviderError
from app.main import app
from tests.fakes import FakeDocumentStorage


client = TestClient(app)


@pytest.fixture
def storage():
    fake_storage = FakeDocumentStorage()
    app.dependency_overrides[get_document_storage] = lambda: fake_storage
    yield fake_storage
    app.dependency_overrides.clear()


def delete_file(path=None):
    params = {}

    if path is not None:
        params["path"] = path

    return client.delete("/files", params=params)


def test_delete_file(storage):
    storage.upload("/docs/report.pdf", b"hello")

    response = delete_file("/docs/report.pdf")

    assert response.status_code == 204
    assert response.content == b""
    assert "/docs/report.pdf" not in storage.files


def test_deleted_file_cannot_be_fetched(storage):
    storage.upload("/report.pdf", b"hello")
    delete_file("/report.pdf")

    response = client.get("/files/metadata", params={"path": "/report.pdf"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_delete_same_path_twice(storage):
    storage.upload("/report.pdf", b"hello")

    first = delete_file("/report.pdf")
    second = delete_file("/report.pdf")

    assert first.status_code == 204
    assert second.status_code == 404
    assert second.json()["error"]["code"] == "not_found"


def test_delete_missing_file(storage):
    response = delete_file("/missing.pdf")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "File not found: /missing.pdf",
        }
    }


def test_delete_without_path(storage):
    response = delete_file()

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_delete_bad_path(storage):
    response = delete_file("report.pdf")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


class FailingStorage(FakeDocumentStorage):

    def __init__(self, error):
        super().__init__()
        self.error = error

    def delete(self, path):
        raise self.error


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (ProviderError("Dropbox is down"), 502, "provider_error"),
        (PermissionDeniedError("No permission"), 403, "permission_denied"),
    ],
)
def test_delete_storage_errors(error, status, code):
    app.dependency_overrides[get_document_storage] = lambda: FailingStorage(error)

    response = delete_file("/report.pdf")
    app.dependency_overrides.clear()

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
