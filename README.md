# Document Storage Agent

FastAPI service for storing and retrieving documents. Dropbox is the first provider.

Routes depend on the `DocumentStorage` contract, not on Dropbox directly. `get_document_storage()` supplies a `DropboxStorage` in production. Tests can substitute `FakeDocumentStorage`. Document routes are not built yet, and the Dropbox `upload`, `get_metadata`, `download`, `move`, and `delete` methods still raise `NotImplementedError`.

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

## Tests

```powershell
pytest
```

Latest run: **9 passed**.

| File | What it checks |
| --- | --- |
| `test_health.py` | `GET /health` returns 200 and `{"status": "ok"}` |
| `test_dependencies.py` | `get_document_storage()` returns a `DropboxStorage` holding the client it was given. Dropbox is not called. |
| `test_storage_foundation.py` | FastAPI can use `FakeDocumentStorage` instead of Dropbox. A missing file returns 404 `not_found`. Each shared exception maps to the status and code in the table above. |

`GET /_test/metadata` exists only inside `test_storage_foundation.py`.

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
