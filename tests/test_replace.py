import pytest
from fastapi.testclient import TestClient

from app.api.routes import replace
from app.dependencies import get_document_storage
from app.errors import FileConflictError, PermissionDeniedError, ProviderError
from app.main import app
from tests.fakes import FakeDocumentStorage


client = TestClient(app)


@pytest.fixture
def storage():
    fake_storage = FakeDocumentStorage()
    app.dependency_overrides[get_document_storage] = lambda: fake_storage
    yield fake_storage
    app.dependency_overrides.clear()


def replace_file(path=None, content=b"new contents"):
    data = {} if path is None else {"path": path}
    return client.put("/files", data=data, files={"file": ("report.pdf", content)})


def test_replace_file(storage):
    original = storage.upload("/docs/report.pdf", b"hello")

    response = replace_file("/docs/report.pdf", b"new contents")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == original.id
    assert body["path"] == "/docs/report.pdf"
    assert body["size"] == len(b"new contents")
    assert storage.download("/docs/report.pdf") == b"new contents"


def test_replace_missing_file_returns_404_and_creates_nothing(storage):
    response = replace_file("/missing.pdf")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert storage.files == {}


def test_replace_without_file_is_rejected(storage):
    storage.upload("/report.pdf", b"hello")

    response = client.put("/files", data={"path": "/report.pdf"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert storage.download("/report.pdf") == b"hello"


def test_replace_without_path_is_rejected(storage):
    response = replace_file(None)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_replace_too_large_is_rejected(storage, monkeypatch):
    storage.upload("/report.pdf", b"hello")
    monkeypatch.setattr(replace, "MAX_UPLOAD_BYTES", 10)

    response = replace_file("/report.pdf", b"x" * 11)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert storage.download("/report.pdf") == b"hello"


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (FileConflictError("File changed while it was being replaced"), 409, "conflict"),
        (PermissionDeniedError("No write permission"), 403, "permission_denied"),
        (ProviderError("Dropbox failed"), 502, "provider_error"),
    ],
)
def test_replace_storage_errors(storage, monkeypatch, error, status, code):
    storage.upload("/report.pdf", b"hello")

    def failing_replace(path, content):
        raise error

    monkeypatch.setattr(storage, "replace", failing_replace)

    response = replace_file("/report.pdf")

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
