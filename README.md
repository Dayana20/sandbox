# Document Storage Agent

FastAPI service for storing and retrieving documents. Dropbox is the first provider.

Routes depend on the `DocumentStorage` contract, not on Dropbox directly. `get_document_storage()` supplies a `DropboxStorage` in production. Tests can substitute `FakeDocumentStorage`. `POST /files` (upload) and `GET /files/metadata` are built. The Dropbox `download`, `move`, and `delete` methods still raise `NotImplementedError`.

## Base

`DocumentStorage` (`app/providers/base.py`):

| Method | Returns |
| --- | --- |
| `upload(path, content)` | `FileResource` |
| `get_metadata(path)` | `FileResource` |
| `download(path)` | `bytes` |
| `move(path, new_path)` | `FileResource` |
| `delete(path)` | `None` |

`FileResource` (`app/models/file.py`) has `id`, `name`, `path`, `size`, and optional `modified_at`.

Storage failures are the exceptions in `app/errors.py`. Import `FileNotFoundError` from there. `app/main.py` returns:

```json
{ "error": { "code": "not_found", "message": "..." } }
```

| Exception | Status | Code |
| --- | --- | --- |
| `InvalidRequestError` | 400 | `invalid_request` |
| `PermissionDeniedError` | 403 | `permission_denied` |
| `FileNotFoundError` | 404 | `not_found` |
| `FileConflictError` | 409 | `conflict` |
| `ProviderError` | 502 | `provider_error` |

## Storage

- `get_document_storage()` creates a Dropbox client from `DROPBOX_ACCESS_TOKEN` and returns `DropboxStorage`.
- `to_file_resource()` maps Dropbox file metadata onto `FileResource`.
- `app/providers/dropbox/error_mapping.py` turns Dropbox SDK errors into the shared exceptions above.
- `FakeDocumentStorage` (`tests/fakes.py`) keeps files in memory and raises `FileNotFoundError` for a missing path.

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

How it works: the route checks `path` with the same `validate_path` as upload and calls `storage.delete()`. `DropboxStorage.delete()` checks the path is a file with `files_get_metadata`, then calls Dropbox `files_delete_v2`. Lookup failures go through `translate_lookup_error`, write failures through `translate_write_error`, and anything else becomes `provider_error`.

## Tests

```powershell
pytest
```

The real Dropbox test is skipped if `DROPBOX_ACCESS_TOKEN` is not set. To run it:

```powershell
pytest tests/integration -v
```

Latest run: **31 passed** (including the real Dropbox upload test).

| File | What it checks |
| --- | --- |
| `test_health.py` | `GET /health` returns 200 and `{"status": "ok"}` |
| `test_dependencies.py` | `get_document_storage()` returns a `DropboxStorage` holding the client it was given. Dropbox is not called. |
| `test_storage_foundation.py` | FastAPI can use `FakeDocumentStorage` instead of Dropbox. A missing file returns 404 `not_found`. Each shared exception maps to the status and code in the table above. |
| `test_upload.py` | `POST /files` with the fake storage: success, missing or bad input, file too large, 409 on duplicate path, Dropbox errors |
| `test_dropbox_upload.py` | `DropboxStorage.upload` with a mocked Dropbox client: correct call and error mapping |
| `integration/test_upload_dropbox.py` | Uploads to real Dropbox, checks the file, then deletes it |
| `test_delete.py` | `DELETE /files` with the fake storage: success, deleted file returns 404, repeated delete, missing file, bad path, Dropbox errors |
| `test_dropbox_delete.py` | `DropboxStorage.delete` with a mocked Dropbox client: correct call and error mapping |
| `integration/test_delete_dropbox.py` | Deletes a real file from Dropbox, checks it is gone, checks a repeated delete returns 404, and checks a folder is refused |

`GET /files/metadata` exists only inside `test_storage_foundation.py`.

## Layout

```
app/
├── main.py                 # App and error handlers
├── dependencies.py         # get_document_storage()
├── errors.py
├── api/routes/health.py
├── models/file.py
└── providers/
    ├── base.py             # DocumentStorage
    └── dropbox/            # client, storage, error_mapping
scripts/verify_dropbox.py
tests/                      # fakes and the tests above
```

## Setup

Python 3.10 or newer. Copy `.env.example` to `.env` and fill it in. `.env` stays local.

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
| `DROPBOX_APP_KEY` | Dropbox app key |
| `DROPBOX_APP_SECRET` | Dropbox app secret |
| `DROPBOX_ACCESS_TOKEN` | Token used to create the Dropbox client |

## Run

```powershell
uvicorn app.main:app --reload
```

Health check: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

Check the Dropbox token with:

```powershell
python -m scripts.verify_dropbox
```

A working token prints the account ID and display name.
