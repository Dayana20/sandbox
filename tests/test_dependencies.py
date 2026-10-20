from unittest.mock import Mock

import pytest

from app.dependencies import get_document_storage, get_dropbox_client
from app.errors import StorageNotConfiguredError
from app.providers.dropbox.storage import DropboxStorage


@pytest.fixture(autouse=True)
def fresh_client_cache():
    get_dropbox_client.cache_clear()
    yield
    get_dropbox_client.cache_clear()


def test_get_document_storage_creates_dropbox_storage(
    monkeypatch,
):
    fake_client = object()

    monkeypatch.setattr(
        "app.dependencies.create_dropbox_client",
        lambda: fake_client,
    )

    storage = get_document_storage()

    assert isinstance(storage, DropboxStorage)
    assert storage.client is fake_client


def test_dropbox_client_is_created_once(monkeypatch):
    create = Mock(return_value=object())
    monkeypatch.setattr("app.dependencies.create_dropbox_client", create)

    first = get_document_storage()
    second = get_document_storage()

    assert first.client is second.client
    create.assert_called_once()


def test_missing_credentials_are_not_cached(monkeypatch):
    fake_client = object()
    create = Mock(side_effect=[StorageNotConfiguredError("not configured"), fake_client])
    monkeypatch.setattr("app.dependencies.create_dropbox_client", create)

    with pytest.raises(StorageNotConfiguredError):
        get_document_storage()

    assert get_document_storage().client is fake_client
