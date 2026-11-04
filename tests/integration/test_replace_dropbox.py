import uuid

import dropbox
import pytest
from fastapi.testclient import TestClient

from dropbox.files import WriteMode

from app.errors import FileNotFoundError
from app.main import app
from app.providers.dropbox.client import (
    create_dropbox_client,
    dropbox_credentials_configured,
)
from app.providers.dropbox.storage import DropboxStorage


# Only runs when Dropbox credentials are in .env
pytestmark = pytest.mark.skipif(
    not dropbox_credentials_configured(),
    reason="Dropbox credentials not set",
)


def put_file(client, path, content):
    return client.put("/files", data={"path": path}, files={"file": ("a.txt", content)})


def test_replace_in_real_dropbox():
    dbx = create_dropbox_client()
    client = TestClient(app)
    folder = f"/integration-tests/replace-{uuid.uuid4().hex}"
    path = f"{folder}/report.txt"
    missing = f"{folder}/missing.txt"

    uploaded = dbx.files_upload(b"first version", path)

    try:
        response = put_file(client, path, b"second version")
        assert response.status_code == 200
        assert response.json()["id"] == uploaded.id
        _, downloaded = dbx.files_download(path)
        assert downloaded.content == b"second version"

        # replace never creates a file
        not_there = put_file(client, missing, b"x")
        assert not_there.status_code == 404
        with pytest.raises(dropbox.exceptions.ApiError):
            dbx.files_get_metadata(missing)
    finally:
        try:
            dbx.files_delete_v2(folder)
        except Exception:
            pass


def test_stale_rev_is_refused_by_real_dropbox():
    # Someone else changes the file between our read of the rev and our
    # write. Dropbox must refuse the write and keep their change.
    dbx = create_dropbox_client()
    folder = f"/integration-tests/replace-{uuid.uuid4().hex}"
    path = f"{folder}/report.txt"

    stale_rev = dbx.files_upload(b"first version", path).rev
    dbx.files_upload(b"someone else's change", path, mode=WriteMode.overwrite)

    try:
        with pytest.raises(dropbox.exceptions.ApiError) as exc_info:
            dbx.files_upload(
                b"our change",
                path,
                mode=WriteMode.update(stale_rev),
                autorename=False,
                strict_conflict=True,
            )
        assert exc_info.value.error.get_path().reason.is_conflict()

        _, downloaded = dbx.files_download(path)
        assert downloaded.content == b"someone else's change"
    finally:
        try:
            dbx.files_delete_v2(folder)
        except Exception:
            pass


def test_replace_after_delete_does_not_recreate_the_file():
    # strict_conflict=True: a rev for a file that was deleted is a conflict,
    # not a new upload.
    dbx = create_dropbox_client()
    folder = f"/integration-tests/replace-{uuid.uuid4().hex}"
    path = f"{folder}/report.txt"

    rev = dbx.files_upload(b"first version", path).rev
    dbx.files_delete_v2(path)

    try:
        with pytest.raises(dropbox.exceptions.ApiError) as exc_info:
            dbx.files_upload(
                b"our change",
                path,
                mode=WriteMode.update(rev),
                autorename=False,
                strict_conflict=True,
            )
        assert exc_info.value.error.get_path().reason.is_conflict()
        with pytest.raises(dropbox.exceptions.ApiError):
            dbx.files_get_metadata(path)

        # and through our storage the missing file is a 404, never created
        with pytest.raises(FileNotFoundError):
            DropboxStorage(dbx).replace(path, b"x")
    finally:
        try:
            dbx.files_delete_v2(folder)
        except Exception:
            pass
