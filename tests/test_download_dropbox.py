from app.providers.dropbox.client import create_dropbox_client
from app.providers.dropbox.storage import DropboxStorage
from app.dependencies import get_document_storage
from app.main import app
from fastapi.testclient import TestClient
import pytest

def test_download_dropbox_folder():
    # Skip the test if Dropbox credentials are not configured
    try:
        client = create_dropbox_client()
    except Exception:
        pytest.skip("Dropbox credentials not configured")

    storage = DropboxStorage(client=client)
    app.dependency_overrides[get_document_storage] = lambda: storage

    test_folder_path = "/test_folder_for_download"

    # Create a folder in Dropbox for testing
    try:
        client.files_create_folder_v2(test_folder_path)
        test_client = TestClient(app)

        # Attempt to download the folder, which should return a 400 error
        response = test_client.get("/files/download", params={"path": test_folder_path})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_request"
    finally:
        # Clean up: delete the test folder in Dropbox
        try:
            # removes the test’s Dropbox override so later tests use the real dependency 
            # and correctly return 503 when credentials are missing
            app.dependency_overrides.pop(get_document_storage, None)
            client.files_delete_v2(test_folder_path)
        except Exception as e:
            print(f"Failed to clean up test folder: {e}")