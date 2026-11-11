from datetime import datetime
from unittest.mock import Mock, call

import pytest
import requests
from dropbox.exceptions import ApiError, InternalServerError
from dropbox.files import (
    DeletedMetadata,
    FileMetadata,
    FolderMetadata,
    ListFolderContinueError,
    ListFolderError,
    ListFolderResult,
    LookupError,
)

from app.errors import (
    FileNotFoundError,
    InvalidOperationError,
    PermissionDeniedError,
    ProviderError,
    ProviderUnavailableError,
)
from app.providers.dropbox.storage import DropboxStorage


def file(path: str, *, size: int = 1) -> FileMetadata:
    name = path.rsplit("/", maxsplit=1)[-1]
    return FileMetadata(
        name=name,
        id=f"id:{name}",
        client_modified=datetime(2026, 11, 10, 14, 30),
        server_modified=datetime(2026, 11, 10, 14, 30),
        rev="abc123def",
        size=size,
        path_lower=path.lower(),
        path_display=path,
    )


def folder(path: str) -> FolderMetadata:
    name = path.rsplit("/", maxsplit=1)[-1]
    return FolderMetadata(
        name=name,
        id=f"id:{name}",
        path_lower=path.lower(),
        path_display=path,
    )


def page(entries, cursor="cursor", has_more=False):
    return ListFolderResult(entries=entries, cursor=cursor, has_more=has_more)


def list_error(error):
    return ApiError("request", ListFolderError.path(error), None, None)


def continue_error(error):
    return ApiError("request", ListFolderContinueError.path(error), None, None)


def test_list_root_maps_to_dropbox_root_and_is_non_recursive():
    client = Mock()
    client.files_list_folder.return_value = page([])

    result = DropboxStorage(client).list_files("/")

    assert result == []
    client.files_list_folder.assert_called_once_with("", recursive=False)
    client.files_list_folder_continue.assert_not_called()
    client.files_get_metadata.assert_not_called()


def test_list_non_root_empty_folder():
    client = Mock()
    client.files_list_folder.return_value = page([])

    assert DropboxStorage(client).list_files("/empty") == []
    client.files_list_folder.assert_called_once_with("/empty", recursive=False)


def test_list_consumes_every_page_converts_types_and_sorts_globally():
    client = Mock()
    client.files_list_folder.return_value = page(
        [file("/docs/z.txt"), folder("/docs/images")],
        cursor="cursor-1",
        has_more=True,
    )
    client.files_list_folder_continue.side_effect = [
        page([file("/docs/B.txt")], cursor="cursor-2", has_more=True),
        page([file("/docs/a.txt", size=9)], cursor="cursor-3", has_more=False),
    ]

    result = DropboxStorage(client).list_files("/docs")

    assert [entry.path for entry in result] == [
        "/docs/B.txt",
        "/docs/a.txt",
        "/docs/images",
        "/docs/z.txt",
    ]
    assert [entry.type for entry in result] == ["file", "file", "folder", "file"]
    assert result[1].size == 9
    assert result[1].modified_at == "2026-11-10T14:30:00Z"
    assert result[1].etag == "abc123def"
    assert result[2].size is None
    assert result[2].modified_at is None
    assert result[2].etag is None
    client.files_list_folder.assert_called_once_with("/docs", recursive=False)
    assert client.files_list_folder_continue.call_args_list == [
        call("cursor-1"),
        call("cursor-2"),
    ]
    client.files_get_metadata.assert_not_called()


@pytest.mark.parametrize(
    ("lookup", "expected"),
    [
        (LookupError.not_found, FileNotFoundError),
        (LookupError.not_folder, InvalidOperationError),
        (LookupError.restricted_content, PermissionDeniedError),
    ],
)
def test_list_translates_folder_lookup_errors(lookup, expected):
    client = Mock()
    client.files_list_folder.side_effect = list_error(lookup)

    with pytest.raises(expected):
        DropboxStorage(client).list_files("/docs")


def test_list_continuation_failure_never_returns_partial_results():
    client = Mock()
    client.files_list_folder.return_value = page(
        [file("/docs/a.txt")], cursor="next", has_more=True
    )
    client.files_list_folder_continue.side_effect = continue_error(
        LookupError.restricted_content
    )

    with pytest.raises(PermissionDeniedError):
        DropboxStorage(client).list_files("/docs")


def test_list_rejects_repeated_cursor_instead_of_looping():
    client = Mock()
    client.files_list_folder.return_value = page([], cursor="same", has_more=True)
    client.files_list_folder_continue.return_value = page(
        [], cursor="same", has_more=True
    )

    with pytest.raises(ProviderError, match="invalid list cursor"):
        DropboxStorage(client).list_files("/docs")

    client.files_list_folder_continue.assert_called_once_with("same")


def test_list_rejects_unsupported_metadata_instead_of_omitting_it():
    client = Mock()
    client.files_list_folder.return_value = page([DeletedMetadata(name="gone")])

    with pytest.raises(ProviderError, match="unsupported list metadata"):
        DropboxStorage(client).list_files("/docs")


def test_list_request_timeout_is_provider_unavailable():
    client = Mock()
    client.files_list_folder.side_effect = requests.ReadTimeout("timed out")

    with pytest.raises(ProviderUnavailableError):
        DropboxStorage(client).list_files("/docs")


def test_list_dropbox_internal_error_is_provider_unavailable():
    client = Mock()
    client.files_list_folder.side_effect = InternalServerError(
        "request", 503, "provider body"
    )

    with pytest.raises(ProviderUnavailableError):
        DropboxStorage(client).list_files("/docs")
