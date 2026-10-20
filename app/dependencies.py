import functools

import dropbox

from app.providers.base import DocumentStorage
from app.providers.dropbox.client import create_dropbox_client
from app.providers.dropbox.storage import DropboxStorage


@functools.cache
def get_dropbox_client() -> dropbox.Dropbox:
    # One client for the whole app. A new client per request would have to
    # fetch a fresh access token with the refresh token every time. If the
    # credentials are missing, the error is raised and nothing is cached.
    return create_dropbox_client()


def get_document_storage() -> DocumentStorage:
    return DropboxStorage(get_dropbox_client())
