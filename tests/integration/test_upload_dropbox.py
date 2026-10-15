import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.providers.dropbox.client import create_dropbox_client


# Only runs when a real Dropbox token is in .env
pytestmark = pytest.mark.skipif(
    not settings.dropbox_access_token,
    reason="DROPBOX_ACCESS_TOKEN not set",
)


def test_upload_to_real_dropbox():
    dbx = create_dropbox_client()
    client = TestClient(app)
    path = f"/integration-tests/upload-{uuid.uuid4().hex}.txt"
    content = b"hello from the upload test"

    try:
        response = client.post(
            "/files",
            data={"path": path},
            files={"file": ("upload.txt", content)},
        )
        assert response.status_code == 201
        assert response.json()["path"] == path

        # check the file in Dropbox has the same bytes
        _, downloaded = dbx.files_download(path)
        assert downloaded.content == content

        # uploading to the same path again should fail
        again = client.post(
            "/files",
            data={"path": path},
            files={"file": ("upload.txt", b"other")},
        )
        assert again.status_code == 409
    finally:
        # delete the test file so the folder stays clean
        try:
            dbx.files_delete_v2(path)
        except Exception:
            pass
