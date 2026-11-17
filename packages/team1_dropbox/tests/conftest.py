"""Shared Dropbox SDK fixtures for standalone-package tests."""

from datetime import datetime
from unittest.mock import Mock

import pytest
from dropbox.files import FileMetadata, FolderMetadata, ListFolderResult

from team1_dropbox import Team1DropboxStorage


@pytest.fixture
def dropbox_client() -> Mock:
    """Return a controlled Dropbox SDK stand-in."""
    return Mock()


@pytest.fixture
def storage(dropbox_client: Mock) -> Team1DropboxStorage:
    """Return the public adapter with an injected client."""
    return Team1DropboxStorage(client=dropbox_client)


def file_metadata(
    path: str = "/docs/report.md",
    *,
    size: int = 5,
    rev: str = "015abcdef",
) -> FileMetadata:
    """Build realistic file metadata."""
    name = path.rsplit("/", maxsplit=1)[-1]
    return FileMetadata(
        id=f"id:{name}",
        name=name,
        path_lower=path.lower(),
        path_display=path,
        client_modified=datetime(2026, 11, 17, 12, 30),
        server_modified=datetime(2026, 11, 17, 12, 30),
        rev=rev,
        size=size,
    )


def folder_metadata(path: str = "/docs") -> FolderMetadata:
    """Build realistic folder metadata."""
    name = path.rsplit("/", maxsplit=1)[-1]
    return FolderMetadata(
        id=f"id:{name}",
        name=name,
        path_lower=path.lower(),
        path_display=path,
    )


def list_page(
    entries: list[FileMetadata | FolderMetadata],
    *,
    cursor: str = "cursor",
    has_more: bool = False,
) -> ListFolderResult:
    """Build one list-folder response page."""
    return ListFolderResult(entries=entries, cursor=cursor, has_more=has_more)
