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

# Set file.size above a monkeypatched small MAX_UPLOAD_BYTES; assert the route raises InvalidRequestError and file.file.read was never called.
def test_upload_file_size_exceeds_max(monkeypatch):
    class FakeFile:
        def __init__(self):
            self.size = 11
            self.read_called = False

        def read(self, n):
            # simulates returning n bytes; it doesn’t read a real file
            self.read_called = True
            return b"x" * n

    class FakeUploadFile:
        def __init__(self):
            self.file = FakeFile()
            self.size = 11

    monkeypatch.setattr(upload, "MAX_UPLOAD_BYTES", 10)
    fake_file = FakeUploadFile()

    with pytest.raises(upload.InvalidRequestError) as exc_info:
        upload.upload_file(file=fake_file, path="/report.pdf", storage=FakeDocumentStorage())

    assert str(exc_info.value) == "File is larger than 150 MB"
    assert not fake_file.file.read_called


def test_upload_file_size_unknown_exceeds_max(monkeypatch):
    class FakeFile:
        def __init__(self):
            self.size = None
            self.read_called_with = None

        def read(self, n):
            self.read_called_with = n
            return b"x" * (n + 1)  # return one more byte than requested

    class FakeUploadFile:
        def __init__(self):
            self.file = FakeFile()
            self.size = None

    monkeypatch.setattr(upload, "MAX_UPLOAD_BYTES", 10)
    fake_file = FakeUploadFile()

    with pytest.raises(upload.InvalidRequestError) as exc_info:
        upload.upload_file(file=fake_file, path="/report.pdf", storage=FakeDocumentStorage())

    assert str(exc_info.value) == "File is larger than 150 MB"
    assert fake_file.file.read_called_with == 11  # MAX_UPLOAD_BYTES + 1