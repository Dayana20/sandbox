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


def test_upload_documents_the_idempotency_errors_and_keeps_the_storage_ones():
    responses = app.openapi()["paths"]["/files"]["post"]["responses"]
    conflict, unavailable = responses["409"]["description"], responses["503"]["description"]

    assert "`conflict`" in conflict
    assert "`provider_not_configured`" in unavailable
    for code in ("idempotency_conflict", "idempotency_in_progress", "idempotency_outcome_unknown"):
        assert code in conflict
    assert "idempotency_unavailable" in unavailable


def test_routes_without_an_idempotency_key_do_not_document_its_errors():
    paths = app.openapi()["paths"]

    for path, method in [("/files", "patch"), ("/files/metadata", "get")]:
        for response in paths[path][method]["responses"].values():
            assert "idempotency" not in response.get("description", "")
