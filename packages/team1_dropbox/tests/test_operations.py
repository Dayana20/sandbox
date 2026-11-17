"""Dropbox operation and metadata-conversion tests."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import call

import pytest
from cloud_storage_api import (
    ConflictError,
    FileInfo,
    InvalidOperationError,
    NotFoundError,
)
from dropbox.exceptions import ApiError
from dropbox.files import (
    GetMetadataError,
    LookupError,
    RelocationError,
    RelocationResult,
    UploadError,
    UploadWriteFailed,
    WriteConflictError,
    WriteError,
    WriteMode,
)

from conftest import file_metadata, folder_metadata, list_page


def upload_error(reason: WriteError) -> ApiError:
    error = UploadError.path(UploadWriteFailed(reason=reason, upload_session_id="session"))
    return ApiError("request", error, None, None)


def metadata_error(reason: LookupError) -> ApiError:
    return ApiError("request", GetMetadataError.path(reason), None, None)


def test_create_success_uses_add_without_autorename(storage, dropbox_client) -> None:
    dropbox_client.files_upload.return_value = file_metadata(size=5)

    result = storage.create("docs/report.md", b"hello")

    assert result == FileInfo(
        id="id:report.md",
        name="report.md",
        path="/docs/report.md",
        size=5,
        modified_at="2026-11-17T12:30:00Z",
        etag="015abcdef",
        type=None,
    )
    dropbox_client.files_upload.assert_called_once_with(
        b"hello",
        "/docs/report.md",
        mode=WriteMode.add,
        autorename=False,
        mute=True,
        strict_conflict=True,
    )


def test_create_existing_file_is_conflict(storage, dropbox_client) -> None:
    dropbox_client.files_upload.side_effect = upload_error(
        WriteError.conflict(WriteConflictError.file)
    )

    with pytest.raises(ConflictError):
        storage.create("/docs/report.md", b"hello")


def test_replace_existing_file_uses_revision_guard(storage, dropbox_client) -> None:
    dropbox_client.files_get_metadata.return_value = file_metadata(rev="012345678")
    dropbox_client.files_upload.return_value = file_metadata(size=3, rev="123456789")

    result = storage.replace("/docs/report.md", b"new")

    assert result.etag == "123456789"
    dropbox_client.files_upload.assert_called_once_with(
        b"new",
        "/docs/report.md",
        mode=WriteMode.update("012345678"),
        autorename=False,
        mute=True,
        strict_conflict=True,
    )


def test_replace_missing_file_never_creates(storage, dropbox_client) -> None:
    dropbox_client.files_get_metadata.side_effect = metadata_error(LookupError.not_found)

    with pytest.raises(NotFoundError):
        storage.replace("/missing.md", b"new")

    dropbox_client.files_upload.assert_not_called()


def test_replace_folder_is_invalid_operation(storage, dropbox_client) -> None:
    dropbox_client.files_get_metadata.return_value = folder_metadata()

    with pytest.raises(InvalidOperationError):
        storage.replace("/docs", b"new")


def test_replace_stale_revision_is_conflict(storage, dropbox_client) -> None:
    dropbox_client.files_get_metadata.return_value = file_metadata(rev="abcdef123")
    dropbox_client.files_upload.side_effect = upload_error(
        WriteError.conflict(WriteConflictError.file)
    )

    with pytest.raises(ConflictError, match="changed"):
        storage.replace("/docs/report.md", b"new")


def test_download_preserves_exact_bytes(storage, dropbox_client) -> None:
    content = b"\x00\xff# Integration Test\r\n"
    dropbox_client.files_download.return_value = (
        file_metadata(size=len(content)),
        SimpleNamespace(content=content),
    )

    assert storage.download("/docs/report.md") == content


def test_get_file_metadata_normalizes_aware_timestamp(storage, dropbox_client) -> None:
    metadata = file_metadata()
    metadata.server_modified = datetime(2026, 11, 17, 12, 30, tzinfo=timezone.utc)
    dropbox_client.files_get_metadata.return_value = metadata

    result = storage.get_metadata("/docs/report.md")

    assert result.modified_at == "2026-11-17T12:30:00Z"
    assert result.type is None


def test_get_folder_metadata_uses_contract_null_fields(storage, dropbox_client) -> None:
    dropbox_client.files_get_metadata.return_value = folder_metadata("/docs")

    result = storage.get_metadata("/docs")

    assert result == FileInfo(
        id="id:docs",
        name="docs",
        path="/docs",
        size=None,
        modified_at=None,
        etag=None,
        type=None,
    )


def test_list_fetches_all_pages_sets_types_and_sorts(storage, dropbox_client) -> None:
    dropbox_client.files_list_folder.return_value = list_page(
        [file_metadata("/docs/z.md"), folder_metadata("/docs/images")],
        cursor="cursor-1",
        has_more=True,
    )
    dropbox_client.files_list_folder_continue.side_effect = [
        list_page([file_metadata("/docs/B.md")], cursor="cursor-2", has_more=True),
        list_page([file_metadata("/docs/a.md")], cursor="done", has_more=False),
    ]

    result = storage.list_files("/docs")

    assert [entry.path for entry in result] == [
        "/docs/B.md",
        "/docs/a.md",
        "/docs/images",
        "/docs/z.md",
    ]
    assert [entry.type for entry in result] == ["file", "file", "folder", "file"]
    assert result[2].size is None
    assert dropbox_client.files_list_folder_continue.call_args_list == [
        call("cursor-1"),
        call("cursor-2"),
    ]


def test_list_root_uses_dropbox_empty_path(storage, dropbox_client) -> None:
    dropbox_client.files_list_folder.return_value = list_page([])

    assert storage.list_files("/") == []

    dropbox_client.files_list_folder.assert_called_once_with("", recursive=False)


def test_move_success_and_preserves_id(storage, dropbox_client) -> None:
    dropbox_client.files_get_metadata.return_value = file_metadata("/docs/report.md")
    dropbox_client.files_move_v2.return_value = RelocationResult(
        metadata=file_metadata("/archive/report.md")
    )

    result = storage.move("/docs/report.md", "/archive/report.md")

    assert result.id == "id:report.md"
    assert result.path == "/archive/report.md"
    dropbox_client.files_move_v2.assert_called_once_with(
        "/docs/report.md", "/archive/report.md", autorename=False
    )


def test_move_occupied_destination_is_conflict(storage, dropbox_client) -> None:
    dropbox_client.files_get_metadata.return_value = file_metadata()
    dropbox_client.files_move_v2.side_effect = ApiError(
        "request",
        RelocationError.to(WriteError.conflict(WriteConflictError.file)),
        None,
        None,
    )

    with pytest.raises(ConflictError):
        storage.move("/docs/report.md", "/archive/report.md")


def test_move_folder_is_invalid_operation(storage, dropbox_client) -> None:
    dropbox_client.files_get_metadata.return_value = folder_metadata()

    with pytest.raises(InvalidOperationError):
        storage.move("/docs", "/archive/docs")

    dropbox_client.files_move_v2.assert_not_called()


def test_delete_file_or_folder_uses_single_dropbox_call(storage, dropbox_client) -> None:
    assert storage.delete("/docs") is None

    dropbox_client.files_delete_v2.assert_called_once_with("/docs")
    dropbox_client.files_get_metadata.assert_not_called()


def test_health_check_makes_real_provider_method_call(storage, dropbox_client) -> None:
    storage.check_health()

    dropbox_client.users_get_current_account.assert_called_once_with()
