import logging
from unittest.mock import Mock

import pytest
from dropbox.exceptions import ApiError, AuthError, InternalServerError
from dropbox.files import FolderMetadata, GetMetadataError, LookupError, UploadError, UploadWriteFailed, WriteError, WriteConflictError

from app.errors import FileConflictError, FileNotFoundError, InvalidRequestError, PermissionDeniedError, ProviderError
from app.providers.dropbox.storage import DropboxStorage


LOGGER = "app.providers.dropbox.error_mapping"


def dropbox_records(caplog):
    return [r for r in caplog.records if r.name == LOGGER]


def test_lookup_failure_is_logged_with_dropbox_detail(caplog):
    client = Mock()
    client.files_get_metadata.side_effect = ApiError(
        "req-123", GetMetadataError.path(LookupError.not_found), None, None
    )
    storage = DropboxStorage(client)

    with caplog.at_level(logging.WARNING, logger=LOGGER), pytest.raises(FileNotFoundError):
        storage.get_metadata("/docs/missing.pdf")

    [record] = dropbox_records(caplog)
    message = record.getMessage()
    assert record.levelno == logging.WARNING
    assert "operation=get_metadata" in message
    assert "missing.pdf" not in message
    assert "error=FileNotFoundError" in message
    assert "not_found" in message
    assert "request_id=req-123" in message


def test_write_conflict_is_logged(caplog):
    client = Mock()
    reason = WriteError.conflict(WriteConflictError.file)
    client.files_upload.side_effect = ApiError(
        "req-9", UploadError.path(UploadWriteFailed(reason, "session")), None, None
    )
    storage = DropboxStorage(client)

    with caplog.at_level(logging.WARNING, logger=LOGGER), pytest.raises(FileConflictError):
        storage.upload("/docs/report.pdf", b"hello")

    [record] = dropbox_records(caplog)
    assert "operation=upload" in record.getMessage()
    assert "error=FileConflictError" in record.getMessage()


def test_dropbox_outage_is_logged_as_error_without_body(caplog):
    client = Mock()
    client.files_download.side_effect = InternalServerError("req-500", 503, "secret-ish body text")
    storage = DropboxStorage(client)

    with caplog.at_level(logging.WARNING, logger=LOGGER), pytest.raises(ProviderError):
        storage.download("/docs/report.pdf")

    [record] = dropbox_records(caplog)
    assert record.levelno == logging.ERROR
    assert "dropbox_error=InternalServerError" in record.getMessage()
    # Free-text bodies can echo the request, so they stay out of the log.
    assert "secret-ish body text" not in record.getMessage()
    # Expected failures should not dump a stack trace.
    assert record.exc_info is None


def test_auth_failure_is_logged_without_token(caplog):
    token = "sl.SUPER-SECRET-TOKEN"
    client = Mock()
    client._oauth2_access_token = token
    client.files_delete_v2.side_effect = AuthError("req-401", "invalid_access_token")
    client.files_get_metadata.side_effect = AuthError("req-401", "invalid_access_token")
    storage = DropboxStorage(client)

    with caplog.at_level(logging.WARNING, logger=LOGGER), pytest.raises(PermissionDeniedError):
        storage.delete("/docs/report.pdf")

    [record] = dropbox_records(caplog)
    assert "error=PermissionDeniedError" in record.getMessage()
    assert token not in caplog.text


def test_move_failure_is_logged_without_paths(caplog):
    client = Mock()
    client.files_get_metadata.side_effect = ApiError(
        "req-7", GetMetadataError.path(LookupError.not_found), None, None
    )
    storage = DropboxStorage(client)

    with caplog.at_level(logging.WARNING, logger=LOGGER), pytest.raises(FileNotFoundError):
        storage.move("/docs/a.pdf", "/archive/a.pdf")

    [record] = dropbox_records(caplog)
    assert "operation=move" in record.getMessage()
    assert "a.pdf" not in record.getMessage()


def test_our_own_refusal_is_not_logged_as_dropbox_error(caplog):
    client = Mock()
    client.files_get_metadata.return_value = Mock(spec=FolderMetadata)
    storage = DropboxStorage(client)

    with caplog.at_level(logging.WARNING, logger=LOGGER), pytest.raises(InvalidRequestError):
        storage.delete("/docs")

    assert dropbox_records(caplog) == []


def test_success_is_not_logged(caplog):
    client = Mock()
    client.files_download.return_value = (Mock(), Mock(content=b"hello"))
    storage = DropboxStorage(client)

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert storage.download("/docs/report.pdf") == b"hello"

    assert dropbox_records(caplog) == []
