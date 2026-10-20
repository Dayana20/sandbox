# Document Storage Agent

FastAPI service for storing and retrieving documents. Dropbox is the first provider.

Routes depend on the `DocumentStorage` contract, not on Dropbox directly. `get_document_storage()` supplies a `DropboxStorage` in production. Tests can substitute `FakeDocumentStorage`. `POST /files` (upload), `PATCH /files` (rename/move), `DELETE /files`, `GET /files/metadata`, and `GET /files/download` (download) are built.

## Base

`DocumentStorage` (`app/providers/base.py`) is the interface between the service and the storage provider. Routes only use this; they don't know Dropbox is behind it.

| Method | Purpose | Input | Returns | Changes Dropbox? | Caller can assume |
| --- | --- | --- | --- | --- | --- |
| `upload(path, content)` | Save a new file | file path, bytes | `FileResource` | Yes | An existing file is never overwritten or renamed |
| `get_metadata(path)` | Look up a file | file path | `FileResource` | No | Only files, not folders |
| `download(path)` | Get a file's contents | file path | `bytes` | No | Bytes are exactly what was uploaded |
| `move(path, new_path)` | Rename or move a file | old path, new path | `FileResource` | Yes | The `id` stays the same; nothing at `new_path` is overwritten |
| `delete(path)` | Delete a file | file path | `None` | Yes | Only files are deleted, never folders |

Paths are absolute inside the Dropbox app folder, e.g. `/docs/report.pdf`.

`FileResource` (`app/models/file.py`) has `id`, `name`, `path`, `size`, and optional `modified_at`.

## Errors

Every failed request returns the same JSON shape, whichever endpoint it came from:

```json
{ "error": { "code": "not_found", "message": "File not found: /docs/report.pdf" } }
```

`code` is the stable part of the contract; callers should branch on it. `message` is a short human-readable explanation and may change. Every response, success or failure, has an `X-Request-ID` header that matches the server's failure log.

| Status | Code | Raised as | When it happens | Retry? |
| --- | --- | --- | --- | --- |
| 400 | `invalid_request` | `InvalidRequestError` | Missing or badly formed input (e.g. `path` without a leading `/`), the path is a folder, a file is over 150 MB, or Dropbox refuses the name | No. Fix the request first |
| 403 | `permission_denied` | `PermissionDeniedError` | The Dropbox app or token isn't allowed to do this, or the token is invalid | No. Fix the app permissions or credentials |
| 404 | `not_found` | `FileNotFoundError` | Nothing exists at `path`, including a repeated delete or move | No |
| 409 | `conflict` | `FileConflictError` | A file already exists at the target path (upload or move) | No. Choose another path |
| 502 | `provider_error` | `ProviderError` | Dropbox failed, timed out, was unreachable, or rate limited us | Yes, after a short wait. For upload, move and delete, first check whether the change already happened |
| 503 | `provider_not_configured` | `StorageNotConfiguredError` | The server has no Dropbox credentials set | Not until the server is configured |

The mapping lives in one place, `ERRORS` in `app/main.py`. Dropbox errors are turned into these exceptions inside `app/providers/dropbox/error_mapping.py`, so callers never see Dropbox exceptions or Dropbox error text.

**Public:** the status code, the `code`, our short `message`, and the request id.

**Internal (server logs only):** the original Dropbox exception and error union, Dropbox's request id, and the operation that failed. Tokens, file contents and Dropbox's free-text messages are never logged or returned.

### Failure logs

`app/main.py` writes one log line for every failed request (logger `app.requests`):

```
request_failed operation=read_metadata error=not_found status=404 provider=no request_id=3f9c...
```

| Field | Meaning |
| --- | --- |
| `operation` | The route that handled the request (`upload_file`, `read_metadata`, `download_file`, `move_file`, `delete_file`) |
| `error` | The error `code` returned to the caller |
| `status` | The HTTP status returned |
| `provider` | `yes` if Dropbox was called and failed, `no` if our own checks rejected the request |
| `request_id` | Same value as the `X-Request-ID` response header. A caller can send its own |

4xx failures are logged at `WARNING`, 5xx at `ERROR`. The line has no error message, query values, request body or credentials, and no stack trace. When Dropbox was involved, the Dropbox-level detail is in the separate `dropbox_error` line below.

## Storage

- `get_document_storage()` creates a Dropbox client from the credentials in `.env` and returns `DropboxStorage`.
- `to_file_resource()` maps Dropbox file metadata onto `FileResource`.
- `app/providers/dropbox/error_mapping.py` turns Dropbox SDK errors into the errors listed in [Errors](#errors).
- `FakeDocumentStorage` (`tests/fakes.py`) keeps files in memory and raises `FileNotFoundError` for a missing path.

## Provider boundary

| Question | Answer |
| --- | --- |
| Which code knows about Dropbox? | Only `app/providers/dropbox/` (`client.py`, `storage.py`, `error_mapping.py`) and the one place that picks the provider, `app/dependencies.py` |
| Which code only uses our own types? | Routes in `app/api/routes/`, `app/models/file.py`, `app/errors.py`, `app/validation.py` |
| Where is the real provider created? | `get_document_storage()` in `app/dependencies.py` builds the Dropbox client and returns a `DropboxStorage` |
| How does it reach the routes? | Each route asks for `storage: DocumentStorage = Depends(get_document_storage)`. Routes never create it themselves |
| How do tests swap it? | `app.dependency_overrides[get_document_storage] = lambda: FakeDocumentStorage()`. No network or credentials needed |
| Where are Dropbox objects translated? | `DropboxStorage.to_file_resource()` turns Dropbox `FileMetadata` into our `FileResource`; `error_mapping.py` turns Dropbox errors into ours |
| What changes to use another provider? | Add a new class with the same five methods (e.g. under `app/providers/gdrive/`) and return it from `get_document_storage()`. Routes and tests don't change |

## Using this for CRUD

Add a route module under `app/api/routes/` and include it from `app/api/router.py`, the same way `health` is included. Inject storage with `Depends(get_document_storage)`. Call the `DocumentStorage` method and return the result. Let the shared exceptions propagate. `app/main.py` already turns them into the JSON error body.

```python
from fastapi import APIRouter, Depends

from app.dependencies import get_document_storage
from app.models.file import FileResource
from app.providers.base import DocumentStorage

router = APIRouter()


@router.get("/files/metadata")
def read_metadata(
    path: str,
    storage: DocumentStorage = Depends(get_document_storage),
) -> FileResource:
    return storage.get_metadata(path)
```

| Action | Call |
| --- | --- |
| Create | `storage.upload(path, content)` |
| Read metadata | `storage.get_metadata(path)` |
| Read bytes | `storage.download(path)` |
| Update path | `storage.move(path, new_path)` |
| Delete | `storage.delete(path)` |

Fill in the matching method on `DropboxStorage`. Use `self.client` for the Dropbox call, `to_file_resource()` for metadata, and **raise** the translator result so the HTTP handlers run:

```python
from dropbox.exceptions import ApiError, DropboxException

from app.providers.dropbox.error_mapping import (
    translate_dropbox_exception,
    translate_lookup_error,
)

try:
    metadata = self.client.files_get_metadata(path)
except ApiError as exc:
    if exc.error.is_path():
        raise translate_lookup_error(exc.error.get_path(), path) from exc
    raise translate_dropbox_exception(exc) from exc
except DropboxException as exc:
    raise translate_dropbox_exception(exc) from exc

return self.to_file_resource(metadata)
```

Use `translate_lookup_error` when a Dropbox lookup fails, and `translate_write_error` when a write fails. Tests should override `get_document_storage` with `FakeDocumentStorage` so they never call Dropbox. `tests/test_storage_foundation.py` shows that override.

Put `@logs_dropbox_errors` on every new `DropboxStorage` method so its Dropbox failures are logged (see [Dropbox error logs](#dropbox-error-logs)).

## Paths

Every route that takes a file path checks it with `validate_path` from `app/validation.py` before calling storage. A bad path returns `400 invalid_request` and Dropbox is never called. The same rules apply to upload, metadata, download, move (both `path` and `new_path`) and delete:

| Rule | Rejected example |
| --- | --- |
| Required | missing or empty |
| Starts with `/` | `docs/report.pdf` |
| Ends with a file name, not `/` | `/docs/`, `/` |
| No empty, `.` or `..` segments | `/docs//a.pdf`, `/docs/./a.pdf`, `/docs/../a.pdf` |

Paths are not normalized or lower-cased; the service passes them to Dropbox exactly as given. Dropbox's own `id:` and `ns:` path forms are not accepted. Dropbox can still refuse a path that passes these checks (for example a name it disallows), which is also returned as `400`.

## Dropbox error logs

When Dropbox fails, the caller gets a short error like `File not found: /docs/a.pdf`. The original Dropbox error is written to the server log instead, one line per failure, by the `logs_dropbox_errors` decorator in `app/providers/dropbox/error_mapping.py`:

```
dropbox_error operation=get_metadata path=/docs/a.pdf error=FileNotFoundError dropbox_error=ApiError: GetMetadataError('path', LookupError('not_found', None)) request_id=4b3f...
```

| Field | Meaning |
| --- | --- |
| `operation` | The `DropboxStorage` method that failed |
| `path` | The path it was called with (the source path for a move) |
| `error` | The error we returned to the caller |
| `dropbox_error` | The Dropbox exception class, plus the typed Dropbox error for API and auth errors |
| `request_id` | Dropbox's id for the request, useful when asking Dropbox support |

`provider_error` failures are logged at `ERROR`; the rest (not found, conflict, bad path, permission) at `WARNING`. No stack traces are printed. The token, file contents and Dropbox's free-text messages are never logged. Checks the service makes itself, such as refusing a folder or a bad path, are not Dropbox failures and are not logged here.

## Upload a file

`POST /files` (form data) returns `201 Created`.

Saves a new file to the Dropbox app folder and returns its metadata. If a file already exists at that path, nothing is changed and you get `409`.

| Field | Required | Description |
| --- | --- | --- |
| `file` | yes | The file to upload |
| `path` | yes | Where to save it, e.g. `/docs/report.pdf` |

Example response:

```json
{
  "id": "id:a4ayc_80_OEAAAAAAAAAXw",
  "name": "report.pdf",
  "path": "/docs/report.pdf",
  "size": 20483,
  "modified_at": "2026-10-05T14:30:00"
}
```

Errors:

| Status | Code | When |
| --- | --- | --- |
| 400 | `invalid_request` | Missing `file` or `path`, bad path, or file over 150 MB |
| 403 | `permission_denied` | Token can't write to Dropbox |
| 409 | `conflict` | A file already exists at `path` |
| 502 | `provider_error` | Dropbox failed |

Try it:

```bash
curl -i -X POST http://127.0.0.1:8000/files -F "file=@report.pdf" -F "path=/docs/report.pdf"
```

How it works: the route checks the input and calls `storage.upload()`. `DropboxStorage.upload()` calls Dropbox `files_upload` with `WriteMode.add` and `autorename=False`, so existing files are never overwritten. The result goes through `to_file_resource()`, so only `id`, `name`, `path`, `size` and `modified_at` are returned. The token comes from `.env`, which is not committed.

## Get file metadata

`GET /files/metadata?path=...` returns `200 OK` with the file's metadata. It only reads; nothing in Dropbox changes.

| Parameter | Required | Description |
| --- | --- | --- |
| `path` | yes | The file to look up, e.g. `/docs/report.pdf` |

Example response:

```json
{
  "id": "id:a4ayc_80_OEAAAAAAAAAXw",
  "name": "report.pdf",
  "path": "/docs/report.pdf",
  "size": 20483,
  "modified_at": "2026-10-05T14:30:00"
}
```

Errors:

| Status | Code | When |
| --- | --- | --- |
| 400 | `invalid_request` | Missing or bad `path`, or `path` is a folder |
| 403 | `permission_denied` | Token can't read this path |
| 404 | `not_found` | Nothing exists at `path` |
| 502 | `provider_error` | Dropbox failed |

Try it:

```bash
curl -i "http://127.0.0.1:8000/files/metadata?path=/docs/report.pdf"
```

How it works: the route in `app/api/routes/read.py` checks `path` with `validate_path` and calls `storage.get_metadata()` on the `DocumentStorage` interface. `DropboxStorage.get_metadata()` calls Dropbox `files_get_metadata`, refuses folders, and returns a `FileResource`. Lookup failures go through `translate_lookup_error`, so a missing file is `404`.


## Download file

`GET /files/download?path=...` returns `200 OK` with the file's raw bytes in the response body. Use it when you need the actual document content instead of the metadata returned by `GET /files/metadata`.

| Parameter | Required | Description |
| --- | --- | --- |
| `path` | yes | The file to download, e.g. `/docs/report.pdf` |

The response returns the original file bytes with `Content-Type: application/octet-stream` and `Content-Disposition: attachment`. The filename is taken from the final segment of the requested path. `Content-Disposition` includes an ASCII `filename` fallback (unsafe or non-ASCII characters are replaced with `_`) and a UTF-8, percent-encoded `filename*` value so clients that support it can use the original filename.

Errors:

| Status | Code | When |
| --- | --- | --- |
| 400 | `invalid_request` | Missing or bad `path` (see [Paths](#paths)), or Dropbox rejects the path as malformed |
| 403 | `permission_denied` | Token can't read or download this path |
| 404 | `not_found` | Nothing exists at `path` |
| 502 | `provider_error` | Dropbox failed |

Try it:

```bash
curl --fail --show-error --output report.pdf \
  "http://127.0.0.1:8000/files/download?path=/docs/report.pdf"
```

How it works: the route in `app/api/routes/download.py` checks `path` with `validate_path`, then calls `storage.download()` through the `DocumentStorage` interface. `DropboxStorage.download()` calls Dropbox `files_download()` and returns the response content bytes. Dropbox lookup errors are translated with `translate_lookup_error`; missing files return `404`, malformed paths return `400`, and restricted paths return `403`. Provider failures return `502`. Unlike the metadata route, this endpoint returns the document bytes rather than a `FileResource` JSON payload.


## Update (rename or move) a file

`PATCH /files?path=...` with a JSON body returns `200 OK` and the file's new metadata.

Renames or moves the file at `path` to `new_path`. The file keeps the same `id` and content. Missing parent folders in `new_path` are created by Dropbox. Folders are refused with `400`, because Dropbox would move everything inside them. An existing file at `new_path` is never overwritten: you get `409` and nothing changes.

| Field | Where | Required | Description |
| --- | --- | --- | --- |
| `path` | query | yes | The file to move, e.g. `/docs/report.pdf` |
| `new_path` | JSON body | yes | Where it should end up, e.g. `/archive/report.pdf`. Must differ from `path` by more than letter case. Dropbox does not support case-only renames like `/a.pdf` -> `/A.pdf`. |

Example response:

```json
{
  "id": "id:a4ayc_80_OEAAAAAAAAAXw",
  "name": "report.pdf",
  "path": "/archive/report.pdf",
  "size": 20483,
  "modified_at": "2026-10-05T14:30:00"
}
```

Errors:

| Status | Code | When | Retry? |
| --- | --- | --- | --- |
| 400 | `invalid_request` | Missing or bad `path`/`new_path`, `new_path` equals `path` ignoring case, `path` is a folder, or Dropbox refuses the name | No, fix the input |
| 403 | `permission_denied` | Token can't move this file or write to `new_path` | No |
| 404 | `not_found` | Nothing exists at `path` | No |
| 409 | `conflict` | Something already exists at `new_path` | No, pick another `new_path` |
| 502 | `provider_error` | Dropbox failed or is rate limiting | Yes, but first check whether the file already moved (a repeat returns `404` if it did) |

Repeating a successful move returns `404`, because the file is no longer at `path`.

Try it:

```bash
curl -i -X PATCH "http://127.0.0.1:8000/files?path=/docs/report.pdf" \
  -H "Content-Type: application/json" -d '{"new_path": "/archive/report.pdf"}'
```

How it works: the route checks both paths with `validate_path` and rejects a `new_path` that matches `path` ignoring case, without calling Dropbox. `DropboxStorage.move()` checks `path` is a file with `files_get_metadata`, then calls `files_move_v2` with `autorename=False`. Source errors (`from_lookup`, `from_write`) are translated against `path`. Destination errors (`to`) are translated against `new_path`, so a conflict message names the destination. Any other relocation error becomes `provider_error`. Cost: 2 Dropbox calls per move. Dropbox moves the file on its side, so the service never downloads or re-uploads the bytes, whatever the file size.

## Delete a file

`DELETE /files?path=...` returns `204 No Content` with no body.

Deletes the file at `path` from the Dropbox app folder. Folders are refused with `400`, because Dropbox would delete everything inside them. The first delete of a path returns `204`. Deleting the same path again returns `404`, because nothing is there any more.

Errors:

| Status | Code | When |
| --- | --- | --- |
| 400 | `invalid_request` | Missing or bad `path`, or `path` is a folder |
| 403 | `permission_denied` | Token can't delete this path |
| 404 | `not_found` | Nothing exists at `path` |
| 502 | `provider_error` | Dropbox failed |

Try it:

```bash
curl -i -X DELETE "http://127.0.0.1:8000/files?path=/docs/report.pdf"
```

How it works: the route checks `path` with `validate_path` and calls `storage.delete()`. `DropboxStorage.delete()` checks the path is a file with `files_get_metadata`, then calls Dropbox `files_delete_v2`. Lookup failures go through `translate_lookup_error`, write failures through `translate_write_error`, and anything else becomes `provider_error`.

## Tests

Fast tests use the in-memory fake and mocked Dropbox clients. They need no Dropbox token and no network:

```powershell
pytest
```

A plain `pytest` leaves out `tests/integration`. Those tests call real Dropbox, so they need Dropbox credentials in `.env` (see Setup). Run them separately:

```powershell
pytest tests/integration -v
```

Without a token they are skipped. They write under `/integration-tests/` and delete what they create.

| File | What it checks |
| --- | --- |
| `test_health.py` | `GET /health` returns 200 and `{"status": "ok"}` |
| `test_dependencies.py` | `get_document_storage()` returns a `DropboxStorage` holding the client it was given. Dropbox is not called. |
| `test_dropbox_client.py` | `create_dropbox_client()` uses the refresh token when set, falls back to an access token, and errors clearly when credentials are missing |
| `test_storage_foundation.py` | FastAPI can use `FakeDocumentStorage` instead of Dropbox. A missing file returns 404 `not_found`. Each shared exception maps to the status and code in the table above. |
| `test_read.py` | `GET /files/metadata` with the fake storage: success, missing file returns 404, missing or bad path, Dropbox errors |
| `test_dropbox_storage.py` | `DropboxStorage.get_metadata` with a mocked Dropbox client: correct call, folder refused, error mapping |
| `integration/test_read_dropbox.py` | Reads metadata of a real Dropbox file and checks a missing path returns 404 |
| `test_validation.py` | `validate_path` accepts good paths and rejects each bad kind. Every route that takes a path returns 400 for each bad path without calling storage. |
| `test_dropbox_error_logging.py` | Dropbox failures are logged once with operation, path, error, Dropbox error and request id. Outages log at `ERROR` without a stack trace or response body. The token is never logged. Our own refusals and successes are not logged. |
| `test_download.py` | `GET /files/download` with fake storage: returned bytes, empty content, missing path/file, and storage errors |
| `test_dropbox_download.py` | `DropboxStorage.download` with a mocked Dropbox client: returned bytes and Dropbox error mapping |
| `test_failure_logging.py` | One failure log line per failed request with operation, code, status, provider and request id; nothing logged on success; no secrets or messages in the log; caller's `X-Request-ID` reused |
| `test_upload.py` | `POST /files` with the fake storage: success, missing or bad input, file too large, 409 on duplicate path, Dropbox errors |
| `test_dropbox_upload.py` | `DropboxStorage.upload` with a mocked Dropbox client: correct call and error mapping |
| `integration/test_upload_dropbox.py` | Uploads to real Dropbox, checks the file, then deletes it |
| `test_delete.py` | `DELETE /files` with the fake storage: success, deleted file returns 404, repeated delete, missing file, bad path, Dropbox errors |
| `test_dropbox_delete.py` | `DropboxStorage.delete` with a mocked Dropbox client: correct call and error mapping |
| `test_update.py` | `PATCH /files` with the fake storage: success, content kept and old path gone, case-only rename refused, repeated move, missing file, 409 without overwrite, invalid input never reaches storage, Dropbox errors |
| `test_dropbox_update.py` | `DropboxStorage.move` with a mocked Dropbox client: correct call, folder refused, error mapping for source and destination |
| `integration/test_update_dropbox.py` | Moves a real file into a new subfolder, checks the id and bytes, checks a repeat returns 404 and a move onto an existing file returns 409 |
| `integration/test_delete_dropbox.py` | Deletes a real file from Dropbox, checks it is gone, checks a repeated delete returns 404, and checks a folder is refused |

## Lint and type check

```powershell
ruff check .
mypy app
```

`pyproject.toml` holds the pytest, ruff, and mypy settings.

## CI

`.github/workflows/ci.yml` runs on pushes and pull requests to `main` and `yashwanth`. It installs `requirements.txt` (direct dependencies pinned to the tested versions) on Python 3.10, then runs `pytest`, `ruff check .`, and `mypy app`. It uses no Dropbox token, so live Dropbox tests are not part of it.

## Layout

```
app/
├── main.py                 # App and error handlers
├── dependencies.py         # get_document_storage()
├── errors.py
├── validation.py           # validate_path(), shared by every route
├── api/routes/            # health, upload, read, download, update, delete
├── models/file.py
└── providers/
    ├── base.py             # DocumentStorage
    └── dropbox/            # client, storage, error_mapping
scripts/                    # verify_dropbox, get_refresh_token
tests/                      # fakes and the tests above
.github/workflows/ci.yml    # pytest, ruff, mypy
pyproject.toml              # pytest, ruff, mypy settings
requirements.txt
.python-version
```

## Setup

Python 3.10 (pinned in `.python-version`; CI uses the same version). Copy `.env.example` to `.env` and fill it in. `.env` stays local.

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

| Variable | Purpose |
| --- | --- |
| `APP_NAME` | API title |
| `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET` | From the Settings tab of your app in the [Dropbox App Console](https://www.dropbox.com/developers/apps) |
| `DROPBOX_REFRESH_TOKEN` | Used with the app key and secret to log in. It does not expire, so the app keeps working. See below. |
| `DROPBOX_ACCESS_TOKEN` | Optional fallback, used only when no refresh token is set. A token generated in the App Console expires after about 4 hours. |

### Dropbox credentials

The app needs the `files.metadata.read`, `files.metadata.write`, `files.content.read` and `files.content.write` permissions (Permissions tab in the App Console).

1. Put `DROPBOX_APP_KEY` and `DROPBOX_APP_SECRET` in `.env`.
2. Run `python -m scripts.get_refresh_token`. Open the URL it prints, click Allow, and paste the code back.
3. Copy the `DROPBOX_REFRESH_TOKEN=...` line it prints into `.env`.

You only do this once. The Dropbox SDK uses the refresh token to get a new access token whenever the old one expires.

## Run

```powershell
uvicorn app.main:app --reload
```

The app starts without Dropbox credentials. They are only read when a file route needs Dropbox.

Health check: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

Check the Dropbox credentials with:

```powershell
python -m scripts.verify_dropbox
```

Working credentials print the account ID and display name.
