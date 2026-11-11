import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.providers.dropbox.client import (
    create_dropbox_client,
    dropbox_credentials_configured,
)


pytestmark = pytest.mark.skipif(
    not dropbox_credentials_configured(),
    reason="Dropbox credentials not set",
)


def test_list_direct_children_in_real_dropbox():
    dbx = create_dropbox_client()
    client = TestClient(app)
    namespace = f"/integration-list-{uuid.uuid4().hex}"
    docs = f"{namespace}/docs"
    images = f"{docs}/images"
    namespace_created = False

    try:
        dbx.files_create_folder_v2(namespace)
        namespace_created = True
        dbx.files_create_folder_v2(docs)
        dbx.files_create_folder_v2(images)
        dbx.files_upload(b"a", f"{docs}/a.txt")
        dbx.files_upload(b"b", f"{docs}/b.txt")
        dbx.files_upload(b"photo", f"{images}/photo.png")

        response = client.get("/files", params={"path": docs.removeprefix("/")})
        missing = client.get("/files", params={"path": f"{namespace}/missing"})
        root = client.get("/files", params={"path": "/"})

        assert response.status_code == 200
        assert [entry["path"] for entry in response.json()] == [
            f"{docs}/a.txt",
            f"{docs}/b.txt",
            images,
        ]
        assert [entry["type"] for entry in response.json()] == [
            "file",
            "file",
            "folder",
        ]
        assert f"{images}/photo.png" not in {
            entry["path"] for entry in response.json()
        }
        assert missing.status_code == 404
        assert root.status_code == 200
        assert namespace in {entry["path"] for entry in root.json()}
    finally:
        if namespace_created:
            dbx.files_delete_v2(namespace)
