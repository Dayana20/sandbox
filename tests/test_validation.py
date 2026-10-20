import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_document_storage
from app.errors import InvalidRequestError
from app.main import app
from app.validation import validate_path


client = TestClient(app)

BAD_PATHS = [
    "docs/report.pdf",       # no leading slash
    "/docs/",                # ends with a slash, so no file name
    "/",                     # root, no file name
    "/docs//report.pdf",     # empty segment
    "/docs/./report.pdf",    # "." segment
    "/docs/../report.pdf",   # ".." segment
    "/..",
    "/docs/report\n.pdf",    # newline
    "/docs/report\x00.pdf",  # null byte
    "/docs/report\t.pdf",    # tab
    "/docs/report\x7f.pdf",  # delete character
]


@pytest.mark.parametrize(
    "path",
    ["/report.pdf", "/docs/report.pdf", "/a/b/c/notes.v2.txt", "/docs/my report.pdf"],
)
def test_valid_path_is_returned_unchanged(path):
    assert validate_path(path) == path


@pytest.mark.parametrize("path", [None, ""])
def test_missing_path_is_rejected(path):
    with pytest.raises(InvalidRequestError, match="path is required"):
        validate_path(path)


@pytest.mark.parametrize("path", BAD_PATHS)
def test_bad_path_is_rejected(path):
    with pytest.raises(InvalidRequestError):
        validate_path(path)


class StorageThatMustNotBeCalled:
    """Fails the test if a route reaches storage with a path it should have rejected."""

    def __getattr__(self, name):
        def called(*args, **kwargs):
            pytest.fail(f"storage.{name} was called with {args}")

        return called


@pytest.fixture
def untouchable_storage():
    app.dependency_overrides[get_document_storage] = StorageThatMustNotBeCalled
    yield
    app.dependency_overrides.clear()


# One request per route that takes a path. Each builds the request with the
# bad path in the place that route reads it from.
ROUTES = {
    "upload": lambda path: client.post("/files", data={"path": path}, files={"file": ("a.txt", b"hi")}),
    "metadata": lambda path: client.get("/files/metadata", params={"path": path}),
    "download": lambda path: client.get("/files/download", params={"path": path}),
    "move source": lambda path: client.patch("/files", params={"path": path}, json={"new_path": "/ok.txt"}),
    "move destination": lambda path: client.patch("/files", params={"path": "/ok.txt"}, json={"new_path": path}),
    "delete": lambda path: client.delete("/files", params={"path": path}),
}


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("path", BAD_PATHS)
def test_every_route_rejects_bad_path_before_storage(untouchable_storage, route, path):
    response = ROUTES[route](path)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
