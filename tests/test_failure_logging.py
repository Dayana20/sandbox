import logging

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_document_storage
from app.errors import ProviderError
from app.main import app
from tests.fakes import FakeDocumentStorage


LOGGER = "app.requests"

client = TestClient(app)


@pytest.fixture
def storage():
    fake_storage = FakeDocumentStorage()
    app.dependency_overrides[get_document_storage] = lambda: fake_storage
    yield fake_storage
    app.dependency_overrides.clear()


def failure_logs(caplog):
    return [r for r in caplog.records if r.name == LOGGER]


class DropboxDownStorage(FakeDocumentStorage):

    def get_metadata(self, path):
        # same shape as DropboxStorage: our error raised from the SDK error
        try:
            raise ConnectionError("token=secret-value connection reset")
        except ConnectionError as exc:
            raise ProviderError("Dropbox is temporarily unavailable") from exc


def test_success_is_not_logged_and_has_request_id(storage, caplog):
    storage.upload("/report.pdf", b"hello")

    with caplog.at_level(logging.INFO, logger=LOGGER):
        response = client.get("/files/metadata", params={"path": "/report.pdf"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert failure_logs(caplog) == []


def test_missing_file_is_logged(storage, caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER):
        response = client.get("/files/metadata", params={"path": "/missing.pdf"})

    assert response.status_code == 404
    [record] = failure_logs(caplog)
    assert record.levelno == logging.WARNING
    assert record.operation == "read_metadata"
    assert record.error_code == "not_found"
    assert record.status == 404
    assert record.provider is False
    assert record.request_id == response.headers["X-Request-ID"]


def test_invalid_input_is_logged(storage, caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER):
        response = client.delete("/files", params={"path": "no-slash.pdf"})

    assert response.status_code == 400
    [record] = failure_logs(caplog)
    assert record.operation == "delete_file"
    assert record.error_code == "invalid_request"
    assert record.status == 400
    assert record.provider is False


def test_provider_failure_is_logged_as_error(caplog):
    app.dependency_overrides[get_document_storage] = lambda: DropboxDownStorage()

    with caplog.at_level(logging.INFO, logger=LOGGER):
        response = client.get("/files/metadata", params={"path": "/report.pdf"})
    app.dependency_overrides.clear()

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "provider_error"
    [record] = failure_logs(caplog)
    assert record.levelno == logging.ERROR
    assert record.error_code == "provider_error"
    assert record.status == 502
    assert record.provider is True


def test_failure_log_has_no_secrets_or_messages(caplog):
    app.dependency_overrides[get_document_storage] = lambda: DropboxDownStorage()

    with caplog.at_level(logging.INFO, logger=LOGGER):
        client.get("/files/metadata", params={"path": "/private/report.pdf"})
    app.dependency_overrides.clear()

    [record] = failure_logs(caplog)
    text = record.getMessage()
    assert "secret-value" not in text
    assert "temporarily unavailable" not in text
    assert "/private/report.pdf" not in text
    assert record.exc_info is None


def test_caller_request_id_is_reused(storage, caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER):
        response = client.get(
            "/files/metadata",
            params={"path": "/missing.pdf"},
            headers={"X-Request-ID": "abc-123"},
        )

    assert response.headers["X-Request-ID"] == "abc-123"
    [record] = failure_logs(caplog)
    assert record.request_id == "abc-123"


def test_error_body_shape_is_unchanged(storage):
    response = client.get("/files/metadata", params={"path": "/missing.pdf"})

    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "File not found: /missing.pdf",
        }
    }
