from app.providers.base import DocumentStorage
from app.providers.dropbox.client import create_dropbox_client
from app.providers.dropbox.storage import DropboxStorage


def get_document_storage() -> DocumentStorage:
    client = create_dropbox_client()

    return DropboxStorage(client)
