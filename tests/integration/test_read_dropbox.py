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


def test_get_metadata_from_real_dropbox():
    dbx = create_dropbox_client()
    client = TestClient(app)
    path = f"/integration-tests/read-{uuid.uuid4().hex}.txt"
    content = b"hello from the metadata test"

    uploaded = dbx.files_upload(content, path)

    try:
        response = client.get("/files/metadata", params={"path": path})
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == uploaded.id
        assert body["path"] == path
        assert body["size"] == len(content)

        # a path that doesn't exist should be 404, not 500
        missing = client.get("/files/metadata", params={"path": path + ".missing"})
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "not_found"
    finally:
        # delete the test file so the folder stays clean
        try:
            dbx.files_delete_v2(path)
        except Exception:
            pass
