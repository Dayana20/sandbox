import pytest

from app.main import app


ERROR_SCHEMA = "#/components/schemas/ErrorResponse"


@pytest.mark.parametrize(
    ("method", "path", "statuses"),
    [
        ("post", "/files", ["400", "403", "409", "502", "503"]),
        ("get", "/files/metadata", ["400", "403", "404", "502", "503"]),
        ("get", "/files/download", ["400", "403", "404", "502", "503"]),
        ("patch", "/files", ["400", "403", "404", "409", "502", "503"]),
        ("delete", "/files", ["400", "403", "404", "502", "503"]),
    ],
)
def test_swagger_lists_real_error_responses(method, path, statuses):
    responses = app.openapi()["paths"][path][method]["responses"]

    for status in statuses:
        schema = responses[status]["content"]["application/json"]["schema"]
        assert schema["$ref"] == ERROR_SCHEMA
