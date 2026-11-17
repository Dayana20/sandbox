"""Contract, namespace and default-streaming tests."""

import ast
import inspect
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import team1_dropbox
from cloud_storage_api import DocumentStorage, FileInfo

from team1_dropbox import Team1DropboxStorage

from conftest import file_metadata


def test_public_import_and_version() -> None:
    assert team1_dropbox.Team1DropboxStorage is Team1DropboxStorage
    assert team1_dropbox.__version__ == "0.1.0"


def test_adapter_is_concrete_contract_subclass() -> None:
    assert issubclass(Team1DropboxStorage, DocumentStorage)
    assert not inspect.isabstract(Team1DropboxStorage)
    storage = Team1DropboxStorage(client=Mock())
    assert isinstance(storage, DocumentStorage)
    assert not storage.__class__.__abstractmethods__


def test_package_source_never_imports_generic_app_namespace() -> None:
    source_root = Path(__file__).parents[1] / "src" / "team1_dropbox"
    for source_file in source_root.glob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        imported_names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names.append(node.module)
        assert all(name != "app" and not name.startswith("app.") for name in imported_names)


def test_metadata_values_are_shared_file_info_instances(storage, dropbox_client) -> None:
    dropbox_client.files_get_metadata.return_value = file_metadata()

    result = storage.get_metadata("/docs/report.md")

    assert type(result) is FileInfo


def test_default_open_download_uses_metadata_and_exact_bytes(storage, dropbox_client) -> None:
    content = b"abcdefgh"
    dropbox_client.files_get_metadata.return_value = file_metadata(size=len(content))
    dropbox_client.files_download.return_value = (
        file_metadata(size=len(content)),
        SimpleNamespace(content=content),
    )

    with storage.open_download("/docs/report.md") as download:
        assert download.info.path == "/docs/report.md"
        assert list(download.chunks(3)) == [b"abc", b"def", b"gh"]

    dropbox_client.files_get_metadata.assert_called_once_with("/docs/report.md")
    dropbox_client.files_download.assert_called_once_with("/docs/report.md")


def test_default_create_stream_reads_current_position_without_closing(
    storage, dropbox_client
) -> None:
    stream = BytesIO(b"prefix-payload")
    stream.seek(7)
    dropbox_client.files_upload.return_value = file_metadata(size=7)

    storage.create_stream("/docs/report.md", stream)

    assert not stream.closed
    assert dropbox_client.files_upload.call_args.args[:2] == (b"payload", "/docs/report.md")


def test_default_replace_stream_reads_bytes_without_closing(storage, dropbox_client) -> None:
    stream = BytesIO(b"replacement")
    dropbox_client.files_get_metadata.return_value = file_metadata(rev="012345678")
    dropbox_client.files_upload.return_value = file_metadata(size=11, rev="123456789")

    result = storage.replace_stream("/docs/report.md", stream)

    assert result.etag == "123456789"
    assert not stream.closed
    assert dropbox_client.files_upload.call_args.args[:2] == (
        b"replacement",
        "/docs/report.md",
    )
