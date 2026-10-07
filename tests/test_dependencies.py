from app.dependencies import get_document_storage
from app.providers.dropbox.storage import DropboxStorage


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
