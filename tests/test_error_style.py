import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_document_storage
from app.main import app
from tests.fakes import FakeDocumentStorage


client = TestClient(app)


@pytest.fixture(autouse=True)
def storage():
    fake_storage = FakeDocumentStorage()
    app.dependency_overrides[get_document_storage] = lambda: fake_storage
    yield fake_storage
    app.dependency_overrides.clear()


def assert_error(response, status, code):
    """Every error has exactly {"error": {"code": str, "message": str}} and nothing else."""
    assert response.status_code == status
    assert response.headers["content-type"] == "application/json"

    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


# One failing request of each kind, for every route. If a new route or a new
# kind of failure answers in a different shape, this table catches it.
CASES = {
    # FastAPI's own routing errors
    "unknown endpoint": (lambda: client.get("/nope"), 404, "not_found"),
    "unknown file sub-path": (lambda: client.get("/files/nope"), 404, "not_found"),
    "wrong method on /files": (lambda: client.put("/files"), 405, "method_not_allowed"),
    "wrong method on /health": (lambda: client.post("/health"), 405, "method_not_allowed"),
    "wrong method on metadata": (lambda: client.delete("/files/metadata"), 405, "method_not_allowed"),
    # Input FastAPI can't parse
    "body is not JSON": (
        lambda: client.patch(
            "/files", params={"path": "/a.txt"}, content=b"{bad", headers={"content-type": "application/json"}
        ),
        400,
        "invalid_request",
    ),
    "new_path is a number": (
        lambda: client.patch("/files", params={"path": "/a.txt"}, json={"new_path": 5}),
        400,
        "invalid_request",
    ),
    "upload file sent as text": (
        lambda: client.post("/files", data={"path": "/a.txt", "file": "x"}),
        400,
        "invalid_request",
    ),
    # Our own checks
    "upload without file": (lambda: client.post("/files", data={"path": "/a.txt"}), 400, "invalid_request"),
    "metadata without path": (lambda: client.get("/files/metadata"), 400, "invalid_request"),
    "download bad path": (lambda: client.get("/files/download", params={"path": "/a/../b"}), 400, "invalid_request"),
    "delete without path": (lambda: client.delete("/files"), 400, "invalid_request"),
    # Missing files, raised by storage
    "metadata missing file": (lambda: client.get("/files/metadata", params={"path": "/no.txt"}), 404, "not_found"),
    "download missing file": (lambda: client.get("/files/download", params={"path": "/no.txt"}), 404, "not_found"),
    "move missing file": (
        lambda: client.patch("/files", params={"path": "/no.txt"}, json={"new_path": "/b.txt"}),
        404,
        "not_found",
    ),
    "delete missing file": (lambda: client.delete("/files", params={"path": "/no.txt"}), 404, "not_found"),
}


@pytest.mark.parametrize("case", CASES)
def test_every_error_has_the_same_shape(case):
    send, status, code = CASES[case]

    assert_error(send(), status, code)


def test_unexpected_bug_has_the_same_shape():
    class BrokenStorage(FakeDocumentStorage):
        def get_metadata(self, path):
            raise RuntimeError("a bug in our code")

    app.dependency_overrides[get_document_storage] = BrokenStorage
    # By default TestClient re-raises server errors; a real caller gets the 500 response
    response = TestClient(app, raise_server_exceptions=False).get("/files/metadata", params={"path": "/a.txt"})

    assert_error(response, 500, "internal_error")


def test_upload_conflict_has_the_same_shape(storage):
    storage.upload("/a.txt", b"old")

    response = client.post("/files", data={"path": "/a.txt"}, files={"file": ("a.txt", b"new")})

    assert_error(response, 409, "conflict")


def test_unknown_endpoint_names_the_request():
    response = client.get("/nope")

    assert response.json()["error"]["message"] == "No such endpoint: GET /nope"


def test_wrong_method_keeps_allow_header():
    response = client.put("/files")

    # Our handler passes on the Allow header FastAPI sets. Known limitation:
    # upload, move and delete are separate routers on /files, and FastAPI only
    # lists the methods of the first one it matches, so this says POST only.
    assert "POST" in response.headers["allow"]


def test_invalid_json_message_is_readable():
    response = client.patch(
        "/files", params={"path": "/a.txt"}, content=b"{bad", headers={"content-type": "application/json"}
    )

    assert response.json()["error"]["message"] == "request body is not valid JSON"


def test_successful_requests_are_unaffected(storage):
    assert client.get("/health").json() == {"status": "ok"}

    response = client.post("/files", data={"path": "/a.txt"}, files={"file": ("a.txt", b"hi")})
    assert response.status_code == 201
    assert response.json()["path"] == "/a.txt"
