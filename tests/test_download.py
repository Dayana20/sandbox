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


def get_file(path):
    response = client.get("/files/download", params={"path": path})
    return response


def test_download_file(storage):
    storage.upload("/docs/test.pdf", b"hello world")

    response = get_file("/docs/test.pdf")

    assert response.status_code == 200
    assert response.content == b'hello world'
    assert response.headers["Content-Disposition"] == 'attachment; filename="test.pdf";filename*=UTF-8\'\'test.pdf'
    assert response.headers["Content-Type"] == "application/octet-stream"


def test_download_file_not_found(storage):
    response = get_file("/docs/missing_file.pdf")

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "File not found: /docs/missing_file.pdf"


def test_download_file_no_path(storage):
    response = get_file(None)

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "path is required"


def test_download_file_permission_denied(storage):
    class FailingStorage(FakeDocumentStorage):
        def download(self, path: str) -> bytes:
            raise PermissionDeniedError("Access denied")

    app.dependency_overrides[get_document_storage] = lambda: FailingStorage()

    response = get_file("/docs/secret.pdf")

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "Access denied"


def test_download_file_provider_error(storage):
    class FailingStorage(FakeDocumentStorage):
        def download(self, path: str) -> bytes:
            raise ProviderError("Provider error")

    app.dependency_overrides[get_document_storage] = lambda: FailingStorage()

    response = get_file("/docs/error.pdf")

    assert response.status_code == 502
    assert response.json()["error"]["message"] == "Provider error"


def test_download_file_empty_content(storage):
    storage.upload("/docs/empty.txt", b"")

    response = get_file("/docs/empty.txt")

    assert response.status_code == 200
    assert response.content == b""


def test_download_storage_error(storage):
    class FailingStorage(FakeDocumentStorage):
        def download(self, path: str) -> bytes:
            raise Exception("Unexpected error")

    app.dependency_overrides[get_document_storage] = lambda: FailingStorage()

    with pytest.raises(Exception, match="Unexpected error"):
        get_file("/docs/unexpected.pdf")


def test_download_file_with_special_characters(storage):
    special_path = "/docs/special_çhår.pdf"
    storage.upload(special_path, b"special content")

    response = get_file(special_path)

    assert response.status_code == 200
    assert response.content == b"special content"


def test_download_file_with_spaces(storage):
    spaced_path = "/docs/file with spaces.pdf"
    storage.upload(spaced_path, b"content with spaces")

    response = get_file(spaced_path)

    assert response.status_code == 200
    assert response.content == b"content with spaces"


def test_download_file_with_long_path(storage):
    long_path = "/docs/" + "a" * 1000 + ".pdf"
    storage.upload(long_path, b"long path content")

    response = get_file(long_path)

    assert response.status_code == 200
    assert response.content == b"long path content"


def test_download_file_with_nested_directories(storage):
    nested_path = "/docs/nested/dir/file.pdf"
    storage.upload(nested_path, b"nested content")

    response = get_file(nested_path)

    assert response.status_code == 200
    assert response.content == b"nested content"


def test_download_file_headers_encode_quotes_and_non_ascii(storage):
    path = '/docs/résumé "final".pdf'
    content = b"original bytes"
    storage.upload(path, content)

    response = get_file(path)

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["Content-Type"] == "application/octet-stream"
    assert response.headers["Content-Disposition"] == (
        'attachment; filename="r_sum_ _final_.pdf";'
        "filename*=UTF-8''r%C3%A9sum%C3%A9%20%22final%22.pdf"
    )

def test_download_file_headers_encode_space(storage):
    path = "/docs/final report.pdf"
    content = b"original bytes"
    storage.upload(path, content)

    response = get_file(path)

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["Content-Type"] == "application/octet-stream"
    assert response.headers["Content-Disposition"] == (
        'attachment; filename="final report.pdf";'
        "filename*=UTF-8''final%20report.pdf"
    )