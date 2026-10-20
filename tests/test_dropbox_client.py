from unittest.mock import Mock

import pytest

from app.core.config import settings
from app.providers.dropbox import client
from app.errors import StorageNotConfiguredError

from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def mock_dropbox(monkeypatch):
    for name in (
        "dropbox_refresh_token",
        "dropbox_access_token",
        "dropbox_app_key",
        "dropbox_app_secret",
    ):
        monkeypatch.setattr(settings, name, None)

    mock = Mock()
    monkeypatch.setattr(client.dropbox, "Dropbox", mock)
    return mock


def test_uses_refresh_token(mock_dropbox, monkeypatch):
    monkeypatch.setattr(settings, "dropbox_refresh_token", "refresh")
    monkeypatch.setattr(settings, "dropbox_app_key", "key")
    monkeypatch.setattr(settings, "dropbox_app_secret", "secret")
    monkeypatch.setattr(settings, "dropbox_access_token", "access")

    result = client.create_dropbox_client()

    mock_dropbox.assert_called_once_with(
        oauth2_refresh_token="refresh",
        app_key="key",
        app_secret="secret",
    )
    assert result is mock_dropbox.return_value


def test_refresh_token_needs_app_key_and_secret(mock_dropbox, monkeypatch):
    monkeypatch.setattr(settings, "dropbox_refresh_token", "refresh")

    with pytest.raises(StorageNotConfiguredError, match="DROPBOX_APP_KEY"):
        client.create_dropbox_client()

    mock_dropbox.assert_not_called()


def test_falls_back_to_access_token(mock_dropbox, monkeypatch):
    monkeypatch.setattr(settings, "dropbox_access_token", "access")

    client.create_dropbox_client()

    mock_dropbox.assert_called_once_with(oauth2_access_token="access")


def test_no_credentials(mock_dropbox):
    assert not client.dropbox_credentials_configured()

    with pytest.raises(StorageNotConfiguredError, match="not configured"):
        client.create_dropbox_client()

def test_dropbox_client_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "dropbox_refresh_token", None)
    monkeypatch.setattr(settings, "dropbox_access_token", None)
    monkeypatch.setattr(settings, "dropbox_app_key", None)
    monkeypatch.setattr(settings, "dropbox_app_secret", None)

    client = TestClient(app)

    response = client.get("/files/download", params={"path": "/docs/test.pdf"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_not_configured"

    response = client.get("/files/download")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_not_configured"

def test_dropbox_client_not_configured_with_bad_path(monkeypatch):
    monkeypatch.setattr(settings, "dropbox_refresh_token", None)
    monkeypatch.setattr(settings, "dropbox_access_token", None)
    monkeypatch.setattr(settings, "dropbox_app_key", None)
    monkeypatch.setattr(settings, "dropbox_app_secret", None)

    client = TestClient(app)

    response = client.get("/files/download", params={"path": "/docs/../report.pdf"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_not_configured"