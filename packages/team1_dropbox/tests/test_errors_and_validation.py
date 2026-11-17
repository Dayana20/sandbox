"""Shared-error translation and path validation tests."""

from unittest.mock import Mock

import pytest
from cloud_storage_api import (
    ConflictError,
    InvalidOperationError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    ProviderError,
    ProviderUnavailableError,
    StorageError,
)
from dropbox.exceptions import ApiError, HttpError, InternalServerError, RateLimitError
from dropbox.files import (
    DeleteError,
    DownloadError,
    GetMetadataError,
    ListFolderError,
    LookupError,
    UploadError,
    UploadWriteFailed,
    WriteConflictError,
    WriteError,
)
from requests.exceptions import ReadTimeout, RequestException

from team1_dropbox import Team1DropboxStorage

from conftest import file_metadata


@pytest.mark.parametrize(
    "path",
    ["", "/", "/docs/", "/docs//a.md", "/docs/../a.md", "/docs/./a.md", "/bad\nname"],
)
def test_file_operations_reject_invalid_paths_before_dropbox(path: str) -> None:
    client = Mock()
    storage = Team1DropboxStorage(client=client)

    with pytest.raises(InvalidRequestError):
        storage.download(path)

    client.files_download.assert_not_called()


def test_content_must_be_bytes() -> None:
    client = Mock()
    storage = Team1DropboxStorage(client=client)

    with pytest.raises(InvalidRequestError, match="bytes"):
        storage.create("/a.txt", "text")  # type: ignore[arg-type]


def test_not_found_maps_to_shared_not_found(storage, dropbox_client) -> None:
    dropbox_client.files_get_metadata.side_effect = ApiError(
        "request", GetMetadataError.path(LookupError.not_found), None, None
    )

    with pytest.raises(NotFoundError) as exc_info:
        storage.get_metadata("/missing.md")

    assert exc_info.value.__class__.__module__ == "cloud_storage_api.errors"


def test_download_folder_maps_to_invalid_operation(storage, dropbox_client) -> None:
    dropbox_client.files_download.side_effect = ApiError(
        "request", DownloadError.path(LookupError.not_file), None, None
    )

    with pytest.raises(InvalidOperationError):
        storage.download("/docs")


def test_list_file_maps_to_invalid_operation(storage, dropbox_client) -> None:
    dropbox_client.files_list_folder.side_effect = ApiError(
        "request", ListFolderError.path(LookupError.not_folder), None, None
    )

    with pytest.raises(InvalidOperationError):
        storage.list_files("/docs/report.md")


def test_permission_failure_maps_to_shared_permission_error(storage, dropbox_client) -> None:
    dropbox_client.files_get_metadata.side_effect = ApiError(
        "request", GetMetadataError.path(LookupError.restricted_content), None, None
    )

    with pytest.raises(PermissionDeniedError):
        storage.get_metadata("/restricted.md")


def test_write_conflict_maps_to_shared_conflict(storage, dropbox_client) -> None:
    error = UploadError.path(
        UploadWriteFailed(
            reason=WriteError.conflict(WriteConflictError.file),
            upload_session_id="session",
        )
    )
    dropbox_client.files_upload.side_effect = ApiError("request", error, None, None)

    with pytest.raises(ConflictError):
        storage.create("/occupied.md", b"x")


def test_delete_missing_maps_to_shared_not_found(storage, dropbox_client) -> None:
    dropbox_client.files_delete_v2.side_effect = ApiError(
        "request", DeleteError.path_lookup(LookupError.not_found), None, None
    )

    with pytest.raises(NotFoundError):
        storage.delete("/missing.md")


@pytest.mark.parametrize(
    "failure",
    [
        ReadTimeout("timeout"),
        InternalServerError("r", 503, "body"),
        HttpError("r", 503, "body"),
    ],
)
def test_unavailable_failures_are_distinguished(storage, dropbox_client, failure) -> None:
    dropbox_client.files_get_metadata.side_effect = failure

    with pytest.raises(ProviderUnavailableError):
        storage.get_metadata("/docs/report.md")


@pytest.mark.parametrize("failure", [RateLimitError("r", None, 1), RequestException("bad")])
def test_other_provider_failures_map_to_provider_error(storage, dropbox_client, failure) -> None:
    dropbox_client.files_get_metadata.side_effect = failure

    with pytest.raises(ProviderError) as exc_info:
        storage.get_metadata("/docs/report.md")

    assert not isinstance(exc_info.value, ProviderUnavailableError)


def test_unexpected_client_exception_does_not_leak(storage, dropbox_client) -> None:
    dropbox_client.files_get_metadata.side_effect = RuntimeError("provider detail")

    with pytest.raises(ProviderError, match="Unexpected") as exc_info:
        storage.get_metadata("/docs/report.md")

    assert "provider detail" not in str(exc_info.value)


def test_health_check_always_uses_unavailable_error(storage, dropbox_client) -> None:
    dropbox_client.users_get_current_account.side_effect = RateLimitError("r", None, 1)

    with pytest.raises(ProviderUnavailableError):
        storage.check_health()


def test_no_application_specific_exception_can_escape() -> None:
    client = Mock()
    client.files_get_metadata.return_value = file_metadata()
    client.files_download.side_effect = RuntimeError("raw provider error")
    storage = Team1DropboxStorage(client=client)

    with pytest.raises(StorageError) as exc_info:
        storage.download("/docs/report.md")

    assert exc_info.value.__class__.__module__.startswith("cloud_storage_api")
