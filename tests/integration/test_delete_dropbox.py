import uuid

import dropbox
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


def test_delete_from_real_dropbox():
    dbx = create_dropbox_client()
    client = TestClient(app)
    path = f"/integration-tests/delete-{uuid.uuid4().hex}.txt"

    dbx.files_upload(b"hello from the delete test", path)

    try:
        response = client.delete("/files", params={"path": path})
        assert response.status_code == 204

        # check the file is gone from Dropbox
        with pytest.raises(dropbox.exceptions.ApiError):
            dbx.files_get_metadata(path)

        # deleting the same path again should be 404
        again = client.delete("/files", params={"path": path})
        assert again.status_code == 404
        assert again.json()["error"]["code"] == "not_found"
    finally:
        # clean up if the delete above failed
        try:
            dbx.files_delete_v2(path)
        except Exception:
            pass


def test_delete_refuses_real_folder():
    dbx = create_dropbox_client()
    client = TestClient(app)
    path = f"/integration-tests/folder-{uuid.uuid4().hex}"

    dbx.files_create_folder_v2(path)

    try:
        response = client.delete("/files", params={"path": path})
        assert response.status_code == 400

        # the folder should still be there
        dbx.files_get_metadata(path)
    finally:
        try:
            dbx.files_delete_v2(path)
        except Exception:
            pass
