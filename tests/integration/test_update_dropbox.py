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


def test_move_in_real_dropbox():
    dbx = create_dropbox_client()
    client = TestClient(app)
    folder = f"/integration-tests/move-{uuid.uuid4().hex}"
    path = f"{folder}/original.txt"
    new_path = f"{folder}/sub/renamed.txt"
    taken = f"{folder}/taken.txt"

    uploaded = dbx.files_upload(b"hello from the move test", path)
    dbx.files_upload(b"already here", taken)

    try:
        response = client.patch("/files", params={"path": path}, json={"new_path": new_path})
        assert response.status_code == 200
        assert response.json()["id"] == uploaded.id
        assert response.json()["path"] == new_path

        # old path is gone, new path has the same bytes
        with pytest.raises(dropbox.exceptions.ApiError):
            dbx.files_get_metadata(path)
        _, downloaded = dbx.files_download(new_path)
        assert downloaded.content == b"hello from the move test"

        # repeating the same move is 404, the source is gone
        again = client.patch("/files", params={"path": path}, json={"new_path": new_path})
        assert again.status_code == 404

        # moving onto an existing file is refused and changes nothing
        conflict = client.patch("/files", params={"path": new_path}, json={"new_path": taken})
        assert conflict.status_code == 409
        _, still_there = dbx.files_download(taken)
        assert still_there.content == b"already here"
    finally:
        try:
            dbx.files_delete_v2(folder)
        except Exception:
            pass
