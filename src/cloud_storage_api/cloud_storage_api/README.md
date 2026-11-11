# Cloud Storage API

`cloud_storage_api` defines a provider-independent Python contract for document
storage. It contains an abstract interface, a shared file metadata model, and
typed storage errors. It does not include a cloud provider implementation or a
factory for creating one.

## Requirements

- Python 3.12 or later
- No runtime dependencies

## Public API

```python
from cloud_storage_api import DocumentStorage, FileInfo
```

Provider adapters implement `DocumentStorage`. Consumers can depend on that
interface instead of a provider-specific client.

### `DocumentStorage`

| Method | Contract |
| --- | --- |
| `create(path, content)` | Create a file and return its `FileInfo`. Raise `ConflictError` if the path already exists. |
| `replace(path, content)` | Replace an existing file and return its `FileInfo`. Raise `NotFoundError` if it is missing; do not create it. |
| `download(path)` | Return the file's exact contents as bytes. |
| `get_metadata(path)` | Return the file's `FileInfo`. Raise `NotFoundError` if it is missing. |
| `list_files(path)` | Return direct children of a folder as `FileInfo` objects, sorted by path. Fetch every page of results. |
| `move(from_path, to_path)` | Move a file and return its `FileInfo`. Raise `ConflictError` if the destination already exists. |
| `delete(path)` | Delete a file, or a folder and everything in it. |
| `check_health()` | Make one lightweight provider call. Raise `ProviderUnavailableError` if it fails. |

### `FileInfo`

`FileInfo` describes a file or folder and has these fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | `str \| None` | Provider ID, or `None` if the provider has none. |
| `name` | `str` | Last segment of the path, such as `report.pdf`. |
| `path` | `str` | Absolute path with a leading slash, such as `/docs/report.pdf`. |
| `size` | `int \| None` | Size in bytes, or `None` for folders. |
| `modified_at` | `str \| None` | ISO 8601 UTC timestamp ending in `Z`, or `None` for folders. |
| `etag` | `str \| None` | Fingerprint that changes when the file changes. |
| `type` | `str \| None` | `"file"` or `"folder"`; set on list entries only. |

### Errors

All errors inherit from `StorageError`, which has a `message`, `status_code`,
and `code`.

| Error | Status | Code | Meaning |
| --- | ---: | --- | --- |
| `InvalidRequestError` | 400 | `invalid_request` | Missing fields or malformed input. |
| `PermissionDeniedError` | 403 | `permission_denied` | The provider refused credentials or permissions. |
| `NotFoundError` | 404 | `not_found` | The requested path does not exist. |
| `ConflictError` | 409 | `conflict` | The destination is occupied or a stale write was refused. |
| `FileTooLargeError` | 413 | `file_too_large` | The upload exceeds the accepted size. |
| `InvalidOperationError` | 422 | `invalid_operation` | The operation is not allowed by the contract. |
| `ProviderError` | 502 | `provider_error` | Another provider failure, or a known partial move or folder deletion. |
| `ProviderUnavailableError` | 503 | `provider_unavailable` | The provider is unreachable or timed out. |

## Usage

Pass a provider adapter to code that depends on the shared interface:

```python
from cloud_storage_api import DocumentStorage, FileInfo


def list_documents(storage: DocumentStorage, folder: str) -> list[FileInfo]:
    return storage.list_files(folder)
```

An adapter must implement every abstract method in `DocumentStorage`, return
`FileInfo` values as specified above, and raise the corresponding storage
errors for contract-defined failures.
