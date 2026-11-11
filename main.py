"""Demonstrate the document storage API."""

from cloud_storage_api import DocumentStorage


def main(storage: DocumentStorage | None = None) -> None:
    """Read-only demonstration using a caller-supplied storage provider."""
    if storage is None:
        print("No storage provider configured. Supply a DocumentStorage adapter to main().")  # noqa: T201
        return

    storage.check_health()
    files = [item for item in storage.list_files("/") if item.type == "file"]

    if not files:
        print("No files found at /.")  # noqa: T201
        return

    file_info = storage.get_metadata(files[0].path)
    content = storage.download(file_info.path)
    print(f"{file_info.name}: {file_info.size} bytes")  # noqa: T201
    print(f"Downloaded {len(content)} bytes.")  # noqa: T201


if __name__ == "__main__":
    main()
