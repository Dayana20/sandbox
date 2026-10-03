# Document Storage Agent

FastAPI service for storing and retrieving documents through pluggable storage providers. Dropbox is the first provider.

This branch, `yashwanth`, holds the storage foundation: the shared contract, the Dropbox provider shell, error translation, and tests that check wiring and HTTP responses.

Document routes that call storage are still to be built. The Dropbox upload, download, metadata, move, and delete methods are still stubs.

## The base

Routes and tests depend on `DocumentStorage` in `app/providers/base.py`. That protocol is the contract every provider implements:

| Method | Returns |
| --- | --- |
| `upload(path, content)` | `FileResource` |
| `get_metadata(path)` | `FileResource` |
| `download(path)` | `bytes` |
| `move(path, new_path)` | `FileResource` |
| `delete(path)` | `None` |

`FileResource` in `app/models/file.py` is the shared description of a stored file: `id`, `name`, `path`, `size`, and optional `modified_at`.

Storage code raises the exceptions in `app/errors.py`. All of them inherit from `StorageError`.

| Exception | Meaning |
| --- | --- |
| `InvalidRequestError` | The path or request is not acceptable |
| `FileNotFoundError` | No file exists at that path |
| `PermissionDeniedError` | The caller cannot read or write the file |
| `FileConflictError` | A write collides with something already at the path |
| `ProviderError` | The storage provider failed |

`FileNotFoundError` here is `app.errors.FileNotFoundError`. Import it from `app.errors`.

`app/main.py` turns those exceptions into this JSON shape:

```json
{
  "error": {
    "code": "not_found",
    "message": "File not found: /notes/a.txt"
  }
}
```

| Exception | HTTP status | `code` |
| --- | --- | --- |
| `InvalidRequestError` | 400 | `invalid_request` |
| `PermissionDeniedError` | 403 | `permission_denied` |
| `FileNotFoundError` | 404 | `not_found` |
| `FileConflictError` | 409 | `conflict` |
| `ProviderError` | 502 | `provider_error` |

## Storage

### Production wiring

`get_document_storage()` in `app/dependencies.py` is what FastAPI will inject into routes:

```text
get_document_storage()
        ↓
create_dropbox_client()
        ↓
DropboxStorage(client)
```

`create_dropbox_client()` reads `DROPBOX_ACCESS_TOKEN` from `.env`. A missing token raises `DROPBOX_ACCESS_TOKEN is not configured`. The Dropbox app key and secret are loaded with the other settings; the client currently uses the access token.

### DropboxStorage

`DropboxStorage` in `app/providers/dropbox/storage.py` holds the Dropbox SDK client. `upload`, `get_metadata`, `download`, `move`, and `delete` raise `NotImplementedError` until the Dropbox calls are filled in.

`to_file_resource()` already maps a Dropbox `FileMetadata` onto `FileResource`:

| Dropbox field | `FileResource` field |
| --- | --- |
| `id` | `id` |
| `name` | `name` |
| `path_display` | `path` |
| `size` | `size` |
| `server_modified` | `modified_at` |

### Dropbox error translation

`app/providers/dropbox/error_mapping.py` converts Dropbox SDK failures into the shared exceptions. Storage methods will call these translators when the Dropbox operations are implemented.

`translate_dropbox_exception()` handles transport and account errors:

| Dropbox exception | Shared exception |
| --- | --- |
| `AuthError` | `PermissionDeniedError` |
| `BadInputError` | `InvalidRequestError` |
| `RateLimitError` | `ProviderError` |
| `InternalServerError` | `ProviderError` |
| any other `DropboxException` | `ProviderError` |

`translate_lookup_error()` handles a Dropbox `LookupError` for a path:

| Dropbox tag | Shared exception |
| --- | --- |
| `not_found` | `FileNotFoundError` |
| `malformed_path` | `InvalidRequestError` |
| `restricted_content` | `PermissionDeniedError` |
| anything else | `ProviderError` |

`translate_write_error()` handles a Dropbox `WriteError` for a path:

| Dropbox tag | Shared exception |
| --- | --- |
| `malformed_path` | `InvalidRequestError` |
| `conflict` | `FileConflictError` |
| `no_write_permission` | `PermissionDeniedError` |
| `disallowed_name` | `InvalidRequestError` |
| anything else | `ProviderError` |

The installed Dropbox SDK `WriteError` has no `is_access_restricted()` method. That branch in `translate_write_error()` raises `AttributeError` if it is reached.

### In-memory fake

`FakeDocumentStorage` in `tests/fakes.py` implements the same five methods in a dictionary. Each path stores a `FileResource` and the file bytes. `upload` uses the path as the id and the last path segment as the name. `move` keeps the original id and content and updates the name and path. A missing path raises `FileNotFoundError` with the message `File not found: {path}`.

Tests use this fake so they can exercise FastAPI without a Dropbox token or network call.

## Tests

From the project root, with the virtual environment active:

```powershell
pytest
```

Latest run: **9 passed**.

### `tests/test_health.py`

Calls `GET /health` and expects status `200` and `{"status": "ok"}`.

### `tests/test_dependencies.py`

Proves the production wiring, with Dropbox replaced by a stand-in client:

```text
get_document_storage()
        ↓
DropboxStorage
        ↓
receives that client
```

`test_get_document_storage_creates_dropbox_storage` patches `create_dropbox_client` so it returns a plain object. It then asserts the result is a `DropboxStorage` and that `storage.client` is that same object. The test does not call the Dropbox API.

### `tests/test_storage_foundation.py`

Proves FastAPI dependency injection and the HTTP error handlers. The file builds its own app with `create_app()` and adds a test-only route, `GET /_test/metadata`. That route is not part of the production API. It asks FastAPI for `DocumentStorage` through `Depends(get_document_storage)` and returns `storage.get_metadata(path)`.

A fixture clears `app.dependency_overrides` before and after every test so one fake cannot leak into the next test.

| Test | Result it checks |
| --- | --- |
| `test_storage_dependency_can_be_replaced` | Overriding `get_document_storage` with `FakeDocumentStorage` makes `GET /_test/metadata?path=/report.pdf` return `200`, name `report.pdf`, path `/report.pdf`, and size `5` |
| `test_missing_file_returns_404` | A missing path returns `404` and `{"error": {"code": "not_found", "message": "File not found: /missing.pdf"}}` |
| `test_storage_errors_are_mapped_to_http` | `InvalidRequestError` → 400 `invalid_request`; `FileNotFoundError` → 404 `not_found`; `PermissionDeniedError` → 403 `permission_denied`; `FileConflictError` → 409 `conflict`; `ProviderError` → 502 `provider_error`. The response message matches the exception text |

`test_storage_errors_are_mapped_to_http` uses `FailingStorage`, a fake whose `get_metadata` raises the exception under test. That covers the full path: storage exception, FastAPI handler, HTTP status, and JSON body.

## Project layout

```
app/
├── main.py                    # FastAPI entry point and error handlers
├── dependencies.py            # get_document_storage()
├── errors.py                  # Storage exceptions
├── api/
│   ├── router.py              # Mounts route modules
│   └── routes/health.py       # GET /health
├── core/config.py             # Environment settings
├── models/file.py             # FileResource
└── providers/
    ├── base.py                # DocumentStorage protocol
    └── dropbox/
        ├── client.py          # Dropbox client factory
        ├── storage.py         # DropboxStorage
        └── error_mapping.py   # Dropbox errors → shared exceptions
scripts/verify_dropbox.py      # Local Dropbox connection check
tests/
├── fakes.py                   # In-memory FakeDocumentStorage
├── test_health.py             # Health endpoint
├── test_dependencies.py       # Production DropboxStorage wiring
└── test_storage_foundation.py # Dependency override and HTTP errors
.env.example                   # Environment variable template
requirements.txt
```

## Setup

Python 3.10 or newer.

```powershell
python -m venv doc
.\doc\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

```bash
python -m venv doc
source doc/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env` on your machine. Keep that file local. It is listed in `.gitignore`.

| Variable | Purpose |
| --- | --- |
| `APP_NAME` | Name shown by the API |
| `DROPBOX_APP_KEY` | Dropbox app key |
| `DROPBOX_APP_SECRET` | Dropbox app secret |
| `DROPBOX_ACCESS_TOKEN` | Token used to create the Dropbox client |

## Run the API

From the project root, with the virtual environment active:

```powershell
uvicorn app.main:app --reload
```

Health check: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

## Verify Dropbox

Set `DROPBOX_ACCESS_TOKEN` in `.env`, then run this from the project root:

```powershell
python -m scripts.verify_dropbox
```

The script creates a Dropbox client and calls `users_get_current_account()`. A working token prints a success message, the account ID, and the account display name.
