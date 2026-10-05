import pytest
from fastapi.testclient import TestClient

from app.api.routes import upload
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


def post_file(path=None, content=None):
    data = {}
    files = None

    if path is not None:
        data["path"] = path
    if content is not None:
        files = {"file": ("test.txt", content)}

    return client.post("/files", data=data, files=files)


def test_upload_file(storage):
    response = post_file("/docs/report.pdf", b"hello")

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "report.pdf"
    assert body["path"] == "/docs/report.pdf"
    assert body["size"] == 5


def test_upload_saves_same_bytes(storage):
    content = bytes(range(256))
    post_file("/data.bin", content)

    assert storage.download("/data.bin") == content


def test_upload_empty_file(storage):
    response = post_file("/empty.txt", b"")

    assert response.status_code == 201
    assert response.json()["size"] == 0


def test_upload_without_path(storage):
    response = post_file(None, b"hello")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


@pytest.mark.parametrize(
    "path",
    ["", "report.pdf", "/docs/", "//report.pdf", "/docs/../report.pdf"],
)
def test_upload_bad_path(storage, path):
    response = post_file(path, b"hello")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_upload_without_file(storage):
    response = post_file("/report.pdf", None)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_upload_too_large(storage, monkeypatch):
    monkeypatch.setattr(upload, "MAX_UPLOAD_BYTES", 10)

    response = post_file("/big.txt", b"x" * 11)

    assert response.status_code == 400


def test_upload_same_path_twice(storage):
    post_file("/report.pdf", b"first")
    response = post_file("/report.pdf", b"second")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert storage.download("/report.pdf") == b"first"


class FailingStorage(FakeDocumentStorage):

    def __init__(self, error):
        super().__init__()
        self.error = error

    def upload(self, path, content):
        raise self.error


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (ProviderError("Dropbox is down"), 502, "provider_error"),
        (PermissionDeniedError("No permission"), 403, "permission_denied"),
    ],
)
def test_upload_storage_errors(error, status, code):
    app.dependency_overrides[get_document_storage] = lambda: FailingStorage(error)

    response = post_file("/report.pdf", b"hello")
    app.dependency_overrides.clear()

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
