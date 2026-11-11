import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_document_storage
from app.errors import PermissionDeniedError, ProviderError, ProviderUnavailableError
from app.main import app
from tests.fakes import FakeDocumentStorage


client = TestClient(app)


@pytest.fixture
def storage():
    fake = FakeDocumentStorage()
    fake.upload("/docs/b.txt", b"b")
    fake.upload("/docs/a.txt", b"a")
    fake.upload("/docs/images/photo.png", b"photo")
    fake.create_folder("/empty")
    app.dependency_overrides[get_document_storage] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


def list_folder(path: str | None):
    params = {} if path is None else {"path": path}
    return client.get("/files", params=params)


def test_list_root_returns_direct_folders_sorted(storage):
    response = list_folder("/")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert response.json() == [
        {
            "id": "/docs",
            "name": "docs",
            "path": "/docs",
            "size": None,
            "modified_at": None,
            "etag": None,
            "type": "folder",
        },
        {
            "id": "/empty",
            "name": "empty",
            "path": "/empty",
            "size": None,
            "modified_at": None,
            "etag": None,
            "type": "folder",
        },
    ]


@pytest.mark.parametrize("path", ["docs", "/docs"])
def test_list_folder_normalizes_path_and_returns_direct_children(storage, path):
    response = list_folder(path)

    assert response.status_code == 200
    body = response.json()
    assert [entry["path"] for entry in body] == [
        "/docs/a.txt",
        "/docs/b.txt",
        "/docs/images",
    ]
    assert [entry["type"] for entry in body] == ["file", "file", "folder"]
    assert "/docs/images/photo.png" not in [entry["path"] for entry in body]
    assert body[-1]["size"] is None
    assert body[-1]["modified_at"] is None
    assert body[-1]["etag"] is None


def test_list_empty_folder_returns_empty_array(storage):
    response = list_folder("/empty")

    assert response.status_code == 200
    assert response.json() == []


def test_list_missing_folder_returns_shared_404(storage):
    response = list_folder("/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_list_file_as_folder_returns_invalid_operation(storage):
    response = list_folder("/docs/a.txt")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_operation"


@pytest.mark.parametrize(
    "path",
    [None, "", ".", "..", "docs/../x", "docs//x", "docs/x/", "docs/\nx"],
)
def test_list_rejects_invalid_paths_before_storage(storage, path):
    response = list_folder(path)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_list_calls_storage_with_canonical_path():
    class RecordingStorage(FakeDocumentStorage):
        seen_path = None

        def list_files(self, path):
            self.seen_path = path
            return []

    storage = RecordingStorage()
    app.dependency_overrides[get_document_storage] = lambda: storage
    try:
        response = list_folder("docs/reports")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert storage.seen_path == "/docs/reports"


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (PermissionDeniedError("denied"), 403, "permission_denied"),
        (ProviderError("failed"), 502, "provider_error"),
        (ProviderUnavailableError("down"), 503, "provider_unavailable"),
    ],
)
def test_list_uses_shared_provider_error_envelope(error, status, code):
    class FailingStorage(FakeDocumentStorage):
        def list_files(self, path):
            raise error

    app.dependency_overrides[get_document_storage] = FailingStorage
    try:
        response = list_folder("/")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == status
    assert response.json() == {"error": {"code": code, "message": str(error)}}


def test_existing_static_get_routes_still_resolve(storage):
    metadata = client.get("/files/metadata", params={"path": "/docs/a.txt"})
    download = client.get("/files/download", params={"path": "/docs/a.txt"})

    assert metadata.status_code == 200
    assert download.status_code == 200
    assert download.content == b"a"


def test_fake_list_reflects_move_and_delete(storage):
    storage.move("/docs/a.txt", "/archive/a.txt")
    storage.delete("/docs/b.txt")

    docs = storage.list_files("/docs")
    archive = storage.list_files("/archive")

    assert [entry.path for entry in docs] == ["/docs/images"]
    assert [entry.path for entry in archive] == ["/archive/a.txt"]
