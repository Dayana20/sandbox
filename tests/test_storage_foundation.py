import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.dependencies import get_document_storage
from app.errors import (
    FileConflictError,
    FileNotFoundError,
    InvalidRequestError,
    PermissionDeniedError,
    ProviderError,
)
from app.main import create_app
from app.models.file import FileResource
from app.providers.base import DocumentStorage
from tests.fakes import FakeDocumentStorage


app = create_app()


@app.get("/_test/metadata")
def get_test_metadata(
    path: str,
    storage: DocumentStorage = Depends(
        get_document_storage
    ),
) -> FileResource:
    return storage.get_metadata(path)


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_dependencies():
    app.dependency_overrides.clear()

    yield

    app.dependency_overrides.clear()


class FailingStorage(FakeDocumentStorage):

    def __init__(self, error: Exception):
        super().__init__()
        self.error = error

    def get_metadata(
        self,
        path: str,
    ) -> FileResource:
        raise self.error


def test_storage_dependency_can_be_replaced():
    fake_storage = FakeDocumentStorage()

    fake_storage.upload(
        "/report.pdf",
        b"hello",
    )

    def override_storage():
        return fake_storage

    app.dependency_overrides[
        get_document_storage
    ] = override_storage

    response = client.get(
        "/_test/metadata",
        params={
            "path": "/report.pdf",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["name"] == "report.pdf"
    assert body["path"] == "/report.pdf"
    assert body["size"] == 5


def test_missing_file_returns_404():
    fake_storage = FakeDocumentStorage()

    def override_storage():
        return fake_storage

    app.dependency_overrides[
        get_document_storage
    ] = override_storage

    response = client.get(
        "/_test/metadata",
        params={
            "path": "/missing.pdf",
        },
    )

    assert response.status_code == 404

    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "File not found: /missing.pdf",
        }
    }


@pytest.mark.parametrize(
    (
        "error",
        "expected_status",
        "expected_code",
    ),
    [
        (
            InvalidRequestError("Invalid path"),
            400,
            "invalid_request",
        ),
        (
            FileNotFoundError("File not found"),
            404,
            "not_found",
        ),
        (
            PermissionDeniedError("Permission denied"),
            403,
            "permission_denied",
        ),
        (
            FileConflictError("File already exists"),
            409,
            "conflict",
        ),
        (
            ProviderError("Dropbox unavailable"),
            502,
            "provider_error",
        ),
    ],
)
def test_storage_errors_are_mapped_to_http(
    error,
    expected_status,
    expected_code,
):
    fake_storage = FailingStorage(error)

    def override_storage():
        return fake_storage

    app.dependency_overrides[
        get_document_storage
    ] = override_storage

    response = client.get(
        "/_test/metadata",
        params={
            "path": "/test.pdf",
        },
    )

    assert response.status_code == expected_status

    body = response.json()

    assert body["error"]["code"] == expected_code
    assert body["error"]["message"] == str(error)
