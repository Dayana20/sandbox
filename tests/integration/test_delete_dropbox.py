import uuid

import dropbox
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


def test_delete_real_folder_with_everything_inside():
    dbx = create_dropbox_client()
    client = TestClient(app)
    folder = f"/integration-tests/folder-{uuid.uuid4().hex}"

    dbx.files_upload(b"one", f"{folder}/a.txt")
    dbx.files_upload(b"two", f"{folder}/sub/b.txt")

    try:
        response = client.delete("/files", params={"path": folder})
        assert response.status_code == 204

        # the folder and the files inside it are gone from Dropbox
        for path in (folder, f"{folder}/a.txt", f"{folder}/sub/b.txt"):
            with pytest.raises(dropbox.exceptions.ApiError):
                dbx.files_get_metadata(path)

        again = client.delete("/files", params={"path": folder})
        assert again.status_code == 404
    finally:
        try:
            dbx.files_delete_v2(folder)
        except Exception:
            pass
