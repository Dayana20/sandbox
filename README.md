# Document Storage Agent

FastAPI service for storing and retrieving documents. Dropbox is the first provider.

**Team 1:** Dayana Alejandro, Shini Agarwal, Annie Jain, Laya Mangalagiri, Yashwanth Kasanneni

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
| 409 | `idempotency_conflict` | `IdempotencyConflictError` | An upload's `Idempotency-Key` was already used for a different request (different `path` or bytes) | No. Use a new key for a different upload |
| 409 | `idempotency_in_progress` | `IdempotencyInProgressError` | The same request with this key is still running, or was cut off. It was not repeated | Yes, later, with the same key |
| 409 | `idempotency_outcome_unknown` | `IdempotencyOutcomeUnknownError` | The first request with this key may have uploaded the file, so it is not repeated | No. Check whether the file exists, then use a new key |
| 502 | `provider_error` | `ProviderError` | Dropbox failed, timed out, was unreachable, or rate limited us | Yes, after a short wait. For upload, move and delete, first check whether the change already happened |
| 503 | `provider_not_configured` | `StorageNotConfiguredError` | The server has no Dropbox credentials set | Not until the server is configured |
| 503 | `idempotency_unavailable` | `IdempotencyUnavailableError` | An upload sent an `Idempotency-Key` but Redis can't be used (not configured, down, or unreadable record). Dropbox was not called | Yes, after a short wait, with the same key |
| 500 | `internal_error` | any other exception | A bug in the service. The message is always `Internal server error`; details stay in the server log | Maybe later; report it with the request id |

The storage errors are mapped in one place, `ERRORS` in `app/main.py`. The four `idempotency_*` errors are not storage errors (the provider was not asked, or not asked again), so they have their own handler in `app/main.py`. It returns the same JSON shape and writes the same `request_failed` log line with `provider=no`, and they are never turned into `internal_error`. Dropbox errors are turned into these exceptions inside `app/providers/dropbox/error_mapping.py`, so callers never see Dropbox exceptions or Dropbox error text.

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

4xx failures are logged at `WARNING`, 5xx at `ERROR`. Unexpected bugs (500) are logged separately as `internal_error method=... path=... status=500 error=<exception type> request_id=...`, without the exception message. The line has no error message, query values, request body or credentials, and no stack trace. When Dropbox was involved, the Dropbox-level detail is in the separate `dropbox_error` line below.

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
| Where is the real provider created? | `get_document_storage()` in `app/dependencies.py` returns a `DropboxStorage` around one Dropbox client that is created on first use and shared by every request |
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
| No control characters (newline, tab, null byte, ...) | `/docs/a\n.pdf` |
| Starts with `/` | `docs/report.pdf` |
| Ends with a file name, not `/` | `/docs/`, `/` |
| No empty, `.` or `..` segments | `/docs//a.pdf`, `/docs/./a.pdf`, `/docs/../a.pdf` |

Paths are not normalized or lower-cased; the service passes them to Dropbox exactly as given. Dropbox's own `id:` and `ns:` path forms are not accepted. Dropbox can still refuse a path that passes these checks (for example a name it disallows), which is also returned as `400`.

## Dropbox error logs

When Dropbox fails, the caller gets a short error like `File not found: /docs/a.pdf`. The original Dropbox error is written to the server log instead, one line per failure, by the `logs_dropbox_errors` decorator in `app/providers/dropbox/error_mapping.py`:

```
dropbox_error operation=get_metadata error=FileNotFoundError dropbox_error=ApiError: GetMetadataError('path', LookupError('not_found', None)) request_id=4b3f...
```

| Field | Meaning |
| --- | --- |
| `operation` | The `DropboxStorage` method that failed |
| `error` | The error we returned to the caller |
| `dropbox_error` | The Dropbox exception class, plus the typed Dropbox error for API and auth errors |
| `request_id` | Dropbox's id for the request, useful when asking Dropbox support |

`provider_error` failures are logged at `ERROR`; the rest (not found, conflict, bad path, permission) at `WARNING`. No stack traces are printed. File paths are not logged, because file names can contain private information. The token, file contents and Dropbox's free-text messages are never logged either. Checks the service makes itself, such as refusing a folder or a bad path, are not Dropbox failures and are not logged here.

## Upload a file

`POST /files` (form data) returns `201 Created`.

Saves a new file to the Dropbox app folder and returns its metadata. If a file already exists at that path, nothing is changed and you get `409`.

| Field | Required | Description |
| --- | --- | --- |
| `file` | yes | The file to upload |
| `path` | yes | Where to save it, e.g. `/docs/report.pdf` |
| `Idempotency-Key` (header) | no | Makes a retry safe. See [Upload idempotency](#upload-idempotency). Leave it out and nothing changes. |

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
| 400 | `invalid_request` | Missing `file` or `path`, bad path, file over 150 MB, or an empty or over-long `Idempotency-Key` |
| 403 | `permission_denied` | Token can't write to Dropbox |
| 409 | `conflict` | A file already exists at `path` |
| 409 | `idempotency_conflict`, `idempotency_in_progress`, `idempotency_outcome_unknown` | Only with an `Idempotency-Key`. See [Upload idempotency](#upload-idempotency) |
| 502 | `provider_error` | Dropbox failed |
| 503 | `idempotency_unavailable` | Only with an `Idempotency-Key`: Redis can't be used, so nothing was uploaded |

Try it:

```bash
curl -i -X POST http://127.0.0.1:8000/files -F "file=@report.pdf" -F "path=/docs/report.pdf"
```

How it works: the route checks the input and calls `storage.upload()`. `DropboxStorage.upload()` calls Dropbox `files_upload` with `WriteMode.add` and `autorename=False`, so existing files are never overwritten. The result goes through `to_file_resource()`, so only `id`, `name`, `path`, `size` and `modified_at` are returned. The token comes from `.env`, which is not committed.

## Upload idempotency

`POST /files` can take an optional `Idempotency-Key` header so a client can retry an upload without risking a second upload.

```bash
curl -i -X POST http://127.0.0.1:8000/files \
  -H "Idempotency-Key: 7d9f1c2e-upload-report" \
  -F "file=@report.pdf" -F "path=/docs/report.pdf"
```

```text
FastAPI upload route
      |
      +--> IdempotencyService --> Redis
      |
      +--> DocumentStorage --> DropboxStorage --> Dropbox
```

Only upload has this. Metadata reads, downloads, moves and deletes do not. `DocumentStorage` and `DropboxStorage` know nothing about idempotency keys: the code is in `app/idempotency/` and is called from the upload route.

### The contract

| | |
| --- | --- |
| Header | `Idempotency-Key: <value>`, optional. With no header the upload behaves exactly as before and never touches Redis |
| Key rules | 1 to 255 characters. An empty or longer key is `400 invalid_request` |
| Scope | The whole service, for the upload operation. One key identifies one logical upload, whoever sends it |
| Redis key | `document-storage:idempotency:upload:<SHA-256 of the key>`. The caller's key is never stored in Redis or logged. Logs show the first 12 characters of the hash as `key_id` |
| Fingerprint | SHA-256 of canonical JSON `{"content_sha256": ..., "operation": "upload", "path": ..., "version": 1}`. So it covers the destination `path` and the file bytes. The file name and content type the client sends are not part of it, because the upload ignores them. The file itself is never stored |
| Record | JSON with `state`, `fingerprint`, an internal `owner` token (see [Reservation ownership](#reservation-ownership)) and, once it has succeeded, the `FileResource` that was returned |
| Retention | `IDEMPOTENCY_TTL_SECONDS`, default `86400` (24 hours). Redis expires the record. The timer starts when the key is reserved (`in_progress`) and restarts each time the state changes. It is not renewed while an upload runs, so it must be longer than the longest upload |

States: `in_progress` (claimed, Dropbox being called), `succeeded` (Dropbox confirmed, result stored) and `uncertain` (Dropbox may have created the file, outcome unknown).

### What each request gets

| Request | State found | Result | Dropbox called? |
| --- | --- | --- | --- |
| New key | none | The upload runs. `201` | Yes, once |
| Same key, same request | `succeeded` | The stored result, `201` | No |
| Same key, different request | any | `409 idempotency_conflict` | No |
| Same key, same request | `in_progress` | `409 idempotency_in_progress`. It does not wait | No |
| Same key, same request | `uncertain` | `409 idempotency_outcome_unknown`: the original may have completed, so it is not repeated | No |
| Any key | Redis can't be used | `503 idempotency_unavailable` | No |

A different request means a different `path` or different bytes. A repeated key is checked against the fingerprint first, so a changed payload is always a conflict, whatever the state. The error messages are fixed. They never contain the key, a fingerprint, a file hash or a Redis message.

### How an upload runs

1. The route checks the file, the `path`, the key and the size, exactly as without a key. A request that fails here is refused before Redis or Dropbox are involved. It claims nothing, so it leaves no record. The caller can fix the input and use the same key.
2. The route reads the file, computes the fingerprint and asks Redis to claim the key. The claim is one `SET ... NX EX`, and it stores a fresh random owner token in the record. Two overlapping requests cannot both claim it, so only one of them can reach Dropbox. A request that finds the key already taken gets no ownership.
3. Only the request that claimed the key calls `storage.upload()`. Then, using its owner token for every change to the record:
   - **Success:** the `FileResource` is stored and the key becomes `succeeded`.
   - **Dropbox proves nothing was uploaded:** the record is deleted and the original error is returned. The same key can be used again. These are the only errors treated this way, because each is an answer Dropbox gave to this request: `invalid_request` (bad path or name), `permission_denied` and `conflict` (a file is already at the path).
   - **Anything else** (`provider_error`, a network failure, an unexpected exception): Dropbox may have received and applied the upload. The key becomes `uncertain`, and the first caller still gets the original error. Retries get `idempotency_outcome_unknown` until the record expires. Nothing is retried automatically.

### Reservation ownership

Each successful claim stores an opaque, random owner token (`uuid4().hex`) in its record. The token identifies that one reservation, not the caller. It stays inside the service: it is never returned to a client and never logged. The only way another request could see it is by reading Redis directly.

Saving `succeeded`, marking `uncertain` and releasing the record are applied only if the record in Redis still carries that request's token. The check and the change are one Redis Lua script, so nothing can change the record between them (there is no Python `GET` followed by `SET` or `DEL`). Without that, this could happen:

```text
A claims key K, then runs longer than the TTL, so A's record expires
B claims K and creates a new in_progress record
A finally finishes. Without ownership, A would overwrite or delete B's record.
```

With ownership, A's late change is skipped in every case:

- **A succeeds late:** A still returns `201`. B's record is left as it is.
- **A fails late** with an uncertain error: A still returns the provider error. It does not mark B's record `uncertain`.
- **A fails late** with a definitive error (conflict, permission, bad request): A still returns that error. It does not delete B's record.
- **No newer record exists** (A's record simply expired): nothing is recreated.

Each skipped change is logged as `idempotency_state_update_skipped` with the operation, the transition that was attempted, the reason (`record_missing` or `owner_changed`) and the short `key_id`. The owner token, fingerprint, response and raw key are not logged.

Ownership only stops an older request from corrupting a newer reservation. It does not stop the second upload itself: once A's record has expired, B is a new request and may upload (see the long-running upload limit below).

### Redis unavailable (fails closed)

When a key is supplied and Redis can't be used, the upload is refused with `503 idempotency_unavailable` and Dropbox is not called. Uploading anyway could create a duplicate while claiming it could not. "Can't be used" covers: `REDIS_URL` not set, Redis down or timing out, and a record we can't read. Redis messages are logged by exception type only and are never returned.

This is the opposite of a cache, where a Redis failure is ignored. Here Redis is part of the correctness of the request.

### Restarts and crashes

Records live in Redis, not in the app, so an app restart forgets nothing: a new process sees the same `succeeded`, `uncertain` and `in_progress` records. If the process dies after the claim, the record stays `in_progress`. Dropbox may or may not have the file, so the upload is not run again. That key stays blocked until the record expires. We chose to risk blocking a retry instead of risking a second upload. There is no background cleanup.

### Guarantees and limits

What this application guarantees (the code in `app/idempotency/`, with tests):

- While the Redis idempotency record is present and unexpired, one key never leads to a second Dropbox upload from this service: not for a repeat, an overlapping request, a restart, or an uncertain outcome. Once the record expires, reuse of the key is treated as a new request.
- A repeat with the same request returns the first result. Reusing a key for a different request is refused.
- A request can only change or delete the record it claimed. If its record expired and another request claimed the key, the older request cannot overwrite, mark `uncertain`, or delete the newer reservation.
- Nothing is uploaded under a key when Redis can't enforce it.
- Raw keys, file contents and file paths are never logged.

What Redis provides: atomic `SET NX`, Lua scripts that run as one atomic step (our owner check plus change), and removing a record when its TTL runs out. Redis knows nothing about uploads. Dropbox provides `WriteMode.add` with `strict_conflict`, which refuses to overwrite a file at the same path. It has no idea about our keys. The idempotency guarantee comes from our integration, not from either of them.

What it does not guarantee:

- **After the TTL:** the record is gone, and the same key is a new request. The guarantee ends with the retention period, and it is not permanent.
- **If Redis loses data** (restart without persistence, eviction, a flush): the records are gone and a retried key uploads again. This code does not configure Redis persistence. Use persistence and a no-eviction policy if you need the guarantee to survive that.
- **Uncertain uploads:** they stay blocked, not resolved. We don't check whether the file exists.
- **If Redis is slow when claiming:** a claim that Redis applied but whose answer timed out is reported as `503`. The key then stays `in_progress` until it expires, although nothing was uploaded. This errs on the side of no duplicates.
- **If the result can't be saved** after a good upload: if Dropbox succeeds but the service cannot write the `succeeded` state to Redis, the original caller still receives `201`, because the upload really happened and reporting a failure would only invite a retry. The record is never falsely marked `succeeded`. It stays `in_progress` (with no stored response and no new TTL) until it expires, and the problem is logged as `idempotency_error operation=save_succeeded`. A later retry with the same key and request gets `409 idempotency_in_progress` and does not call Dropbox again, because the service cannot prove to that caller that the first upload was recorded. The cost is that the retry cannot get the stored result until the key expires.
- **Long-running uploads:** the service does not renew an in-progress reservation while an upload is running. If an upload lasts longer than the configured TTL, the reservation may expire before the upload completes. A request with the same key that arrives after that finds no record, claims the key, and can start a second upload. There is no heartbeat, lease renewal or distributed lock. Set `IDEMPOTENCY_TTL_SECONDS` well above the longest upload. Ownership does not remove this limit (see Reservation ownership).
- **Uploads with no key** are not protected at all.

### Try it

Fast tests use `fakeredis` (with `lupa`, which lets it run the Lua scripts) and need no Redis server (see Tests). To see it against a real Redis and Dropbox:

```bash
docker run --rm -p 6379:6379 redis:7-alpine
python -m scripts.demo_idempotency      # uses REDIS_URL, default redis://localhost:6379/0
```

It uploads once, replays, sends a changed payload, simulates a restart and an unreachable Redis, and prints how many times Dropbox was asked to upload at each step. It deletes the Dropbox file and the Redis record afterwards.

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
| `test_dependencies.py` | `get_document_storage()` returns a `DropboxStorage` holding the client it was given, creates the client only once, and retries if credentials were missing. Dropbox is not called. |
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
| `test_upload_idempotency.py` | Upload with `Idempotency-Key`, using `fakeredis` and a counting fake provider: first request, replay with the provider called once, conflicting payload or path, overlapping requests (a blocked upload, no sleeps), a new service over the same Redis (restart), uncertain outcomes never retried, reservation ownership (a stale request cannot overwrite, mark uncertain or delete a newer reservation, and the owner check runs inside Redis), local rejections leaving no record, Dropbox's definitive errors releasing the key, Redis down or unset failing closed, TTL, no-key uploads unchanged, logs without the raw key or the file path, and the four `idempotency_*` errors using the shared error shape, `X-Request-ID` and `request_failed` log (never a 500, and a Redis outage is not logged as a Dropbox failure) |
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

`.github/workflows/ci.yml` runs on pushes and pull requests to `main`, `yashwanth` and `milestone-3`. It installs `requirements.txt` (direct dependencies pinned to the tested versions) on Python 3.10, then runs `pytest`, `ruff check .`, and `mypy app`. It uses no Dropbox token, so live Dropbox tests are not part of it.

## Layout

```
app/
├── main.py                 # App and error handlers
├── dependencies.py         # get_document_storage(), get_idempotency_service()
├── errors.py
├── validation.py           # validate_path(), shared by every route
├── api/routes/            # health, upload, read, download, update, delete
├── idempotency/            # upload Idempotency-Key: service, redis_store, redis_client
├── models/file.py
└── providers/
    ├── base.py             # DocumentStorage
    └── dropbox/            # client, storage, error_mapping
scripts/                    # verify_dropbox, get_refresh_token, demo_idempotency
tests/                      # fakes and the tests above
.github/workflows/ci.yml    # pytest, ruff, mypy
pyproject.toml              # pytest, ruff, mypy settings
requirements.txt
.python-version
```

## Setup

Python 3.10 (pinned in `.python-version`; CI uses the same version). Copy `.env.example` to `.env` and fill it in. `.env` stays local.

Windows (PowerShell):

```powershell
python -m venv doc
.\doc\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

macOS / Linux (bash or zsh):

```bash
python -m venv doc
source doc/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

If you also have Anaconda installed, its `pytest`, `ruff` or `mypy` can run instead of the ones in `doc`. Run `python -m pytest` (and `python -m ruff`, `python -m mypy`) after activating `doc` to be sure you use the venv's copies.

| Variable | Purpose |
| --- | --- |
| `APP_NAME` | API title |
| `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET` | From the Settings tab of your app in the [Dropbox App Console](https://www.dropbox.com/developers/apps) |
| `DROPBOX_REFRESH_TOKEN` | Used with the app key and secret to log in. It does not expire, so the app keeps working. See below. |
| `DROPBOX_ACCESS_TOKEN` | Optional fallback, used only when no refresh token is set. A token generated in the App Console expires after about 4 hours. |
| `REDIS_URL` | Only needed for uploads that send an `Idempotency-Key`, e.g. `redis://localhost:6379/0`. Without it those uploads get `503`. Other requests don't use Redis. |
| `IDEMPOTENCY_TTL_SECONDS` | How long an Idempotency-Key is remembered. Default `86400` (24 hours). Must be a positive number. |

### Dropbox credentials

Create a Dropbox app:

1. Open the [Dropbox App Console](https://www.dropbox.com/developers/apps) and click **Create app**.
2. Choose **Scoped access**, then **App folder** (the app can only see its own folder, `Apps/<app name>`), and give it any name.
3. On the **Permissions** tab, tick `files.metadata.read`, `files.metadata.write`, `files.content.read` and `files.content.write`, then click **Submit**.
4. The **Settings** tab shows the **App key** and **App secret**.

Then get a refresh token:

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
