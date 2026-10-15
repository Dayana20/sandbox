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


def move_file(path=None, new_path=None):
    params = {}
    body = {}

    if path is not None:
        params["path"] = path
    if new_path is not None:
        body["new_path"] = new_path

    return client.patch("/files", params=params, json=body)


def test_move_file(storage):
    original = storage.upload("/docs/report.pdf", b"hello")

    response = move_file("/docs/report.pdf", "/archive/final.pdf")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == original.id
    assert body["name"] == "final.pdf"
    assert body["path"] == "/archive/final.pdf"
    assert body["size"] == 5


def test_moved_file_keeps_content_and_old_path_is_gone(storage):
    storage.upload("/report.pdf", b"hello")

    move_file("/report.pdf", "/renamed.pdf")

    assert storage.download("/renamed.pdf") == b"hello"
    old = client.get("/files/metadata", params={"path": "/report.pdf"})
    assert old.status_code == 404


def test_case_only_rename_is_refused(storage):
    storage.upload("/report.pdf", b"hello")

    response = move_file("/report.pdf", "/Report.pdf")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert list(storage.files) == ["/report.pdf"]


def test_move_same_request_twice(storage):
    storage.upload("/report.pdf", b"hello")

    first = move_file("/report.pdf", "/renamed.pdf")
    second = move_file("/report.pdf", "/renamed.pdf")

    assert first.status_code == 200
    assert second.status_code == 404
    assert second.json()["error"]["code"] == "not_found"


def test_move_missing_file(storage):
    response = move_file("/missing.pdf", "/renamed.pdf")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "File not found: /missing.pdf",
        }
    }


def test_move_onto_existing_file_is_refused(storage):
    storage.upload("/a.pdf", b"aaa")
    storage.upload("/b.pdf", b"bbb")

    response = move_file("/a.pdf", "/b.pdf")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    # neither file changed
    assert storage.download("/a.pdf") == b"aaa"
    assert storage.download("/b.pdf") == b"bbb"


@pytest.mark.parametrize(
    ("path", "new_path"),
    [
        (None, "/renamed.pdf"),
        ("/report.pdf", None),
        ("report.pdf", "/renamed.pdf"),
        ("/report.pdf", "/folder/"),
        ("/report.pdf", "/../renamed.pdf"),
        ("/report.pdf", "/report.pdf"),
    ],
)
def test_move_invalid_input_never_touches_storage(storage, path, new_path):
    storage.upload("/report.pdf", b"hello")

    response = move_file(path, new_path)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert list(storage.files) == ["/report.pdf"]


@pytest.mark.parametrize(
    "request_kwargs",
    [
        {"json": {"new_path": 123}},
        {"content": b"not json", "headers": {"Content-Type": "application/json"}},
    ],
)
def test_move_badly_typed_body_uses_error_shape(storage, request_kwargs):
    storage.upload("/report.pdf", b"hello")

    response = client.patch("/files", params={"path": "/report.pdf"}, **request_kwargs)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert list(storage.files) == ["/report.pdf"]


class FailingStorage(FakeDocumentStorage):

    def __init__(self, error):
        super().__init__()
        self.error = error

    def move(self, path, new_path):
        raise self.error


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (ProviderError("Dropbox is down"), 502, "provider_error"),
        (PermissionDeniedError("No permission"), 403, "permission_denied"),
    ],
)
def test_move_storage_errors(error, status, code):
    app.dependency_overrides[get_document_storage] = lambda: FailingStorage(error)

    response = move_file("/report.pdf", "/renamed.pdf")
    app.dependency_overrides.clear()

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
