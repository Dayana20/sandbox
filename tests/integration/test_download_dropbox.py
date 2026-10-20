import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.providers.dropbox.client import (
    create_dropbox_client,
    dropbox_credentials_configured,
)


# Only runs when Dropbox credentials are in .env
pytestmark = pytest.mark.skipif(
    not dropbox_credentials_configured(),
    reason="Dropbox credentials not set",
)


def test_download_refuses_real_folder():
    dbx = create_dropbox_client()
    client = TestClient(app)
    path = f"/integration-tests/download-folder-{uuid.uuid4().hex}"

    dbx.files_create_folder_v2(path)

    try:
        response = client.get("/files/download", params={"path": path})

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_request"
    finally:
        try:
            dbx.files_delete_v2(path)
        except Exception:
            pass
