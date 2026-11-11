from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_document_storage
from app.errors import ProviderUnavailableError


client = TestClient(app)

def fake_get_document_storage_error():
    class FakeStorage:
        def check_health(self):
            raise ProviderUnavailableError("Storage provider is unavailable")
    return FakeStorage()

def fake_get_document_storage_success():
    class FakeStorage:
        def check_health(self):
            pass
    return FakeStorage()

def test_check_health():
    app.dependency_overrides[get_document_storage] = fake_get_document_storage_success
    response = client.get("/health/storage")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    app.dependency_overrides.clear()


def test_check_health_with_unavailable_storage():
    # Override the dependency to simulate an unavailable storage provider
    app.dependency_overrides[get_document_storage] = fake_get_document_storage_error

    response = client.get("/health/storage")
    assert response.status_code == 503
    assert response.json() == {"error": {"code": "provider_unavailable", "message": "Storage provider is unavailable"}}

    # Clear the dependency override after the test
    app.dependency_overrides.clear()