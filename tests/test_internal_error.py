import logging

from fastapi.testclient import TestClient

from app.dependencies import get_document_storage
from app.errors import ProviderError
from app.main import create_app
from app.models.file import FileResource
from tests.fakes import FakeDocumentStorage


class FailingStorage(FakeDocumentStorage):

    def __init__(self, error: Exception):
        super().__init__()
        self.error = error

    def get_metadata(self, path: str) -> FileResource:
        raise self.error


def make_client(error: Exception) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_document_storage] = lambda: FailingStorage(error)

    # Starlette sends the 500 response and then re-raises the exception so
    # servers can log it. Keep it from being raised inside the test.
    return TestClient(app, raise_server_exceptions=False)


def test_unexpected_error_returns_internal_error(caplog):
    client = make_client(RuntimeError("unexpected bug"))

    with caplog.at_level(logging.ERROR, logger="app.main"):
        response = client.get("/files/metadata", params={"path": "/report.pdf"})

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "Internal server error",
        }
    }
    assert "unexpected bug" not in response.text

    # The failure is logged with the request and exception type, not the message.
    assert "internal_error" in caplog.text
    assert "method=GET" in caplog.text
    assert "path=/files/metadata" in caplog.text
    assert "status=500" in caplog.text
    assert "error=RuntimeError" in caplog.text
    assert "unexpected bug" not in caplog.text
    assert "report.pdf" not in caplog.text


def test_expected_errors_are_not_caught_by_catch_all():
    client = make_client(ProviderError("Dropbox unavailable"))

    response = client.get("/files/metadata", params={"path": "/report.pdf"})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "provider_error"
