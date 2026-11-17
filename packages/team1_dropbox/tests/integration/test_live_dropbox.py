"""Opt-in integration test against a disposable Dropbox account."""

import os
import uuid

import pytest

from team1_dropbox import Team1DropboxStorage

REQUIRED_ENV = (
    "DROPBOX_APP_KEY",
    "DROPBOX_APP_SECRET",
    "DROPBOX_REFRESH_TOKEN",
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        any(not os.getenv(name) for name in REQUIRED_ENV),
        reason="Disposable Dropbox integration credentials are not configured",
    ),
]


def test_create_download_delete_markdown_file() -> None:
    storage = Team1DropboxStorage.from_env()
    path = f"/team1-package-integration/{uuid.uuid4().hex}.md"
    content = b"# Team 5 integration test\n"
    created = False

    try:
        info = storage.create(path, content)
        created = True
        assert info.path == path
        assert storage.download(path) == content
    finally:
        if created:
            storage.delete(path)
