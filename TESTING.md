# Testing

What we test, why those cases, how to run them, and what is not covered yet. The per-file list of tests is in the [README](README.md#tests); this page explains the strategy behind it.

## Run the tests

```bash
source doc/bin/activate        # Windows: .\doc\Scripts\Activate.ps1
python -m pytest               # fast suite: no Dropbox, no network
python -m pytest tests/integration -v   # real Dropbox, needs .env (see README Setup)
python -m ruff check .         # lint
python -m mypy app             # type check
```

Use `python -m pytest`, not `pytest`, so the virtualenv's pytest runs (Anaconda's can win otherwise).

| Suite | Command | Needs | Runs in CI | When to run |
| --- | --- | --- | --- | --- |
| Fast | `python -m pytest` | nothing | yes | before every commit |
| Live Dropbox | `python -m pytest tests/integration -v` | Dropbox credentials in `.env` | no | before merging a change to `app/providers/dropbox/`, and when verifying a release |

`pyproject.toml` leaves `tests/integration` out of a plain `pytest`. The live tests skip themselves when credentials are missing, write only under `/integration-tests/` with random file names, and delete what they create in a `finally` block, so a failed test does not leave files behind.

CI (`.github/workflows/ci.yml`) runs the fast suite, ruff and mypy on every push and PR to `main`, `yashwanth` and `milestone-3`. It has no Dropbox credentials.

## Test layers

Each layer answers a different question, so a bug shows up in the layer that owns it.

| Layer | What stands in for Dropbox | What it proves | Files |
| --- | --- | --- | --- |
| Application rules | nothing, plain function calls | Path rules are right on their own | `test_validation.py` |
| HTTP API | `FakeDocumentStorage` (in-memory), injected with `app.dependency_overrides[get_document_storage]` | Status codes, response bodies, error shape, and that bad input never reaches storage | `test_upload.py`, `test_read.py`, `test_download.py`, `test_update.py`, `test_delete.py`, `test_error_style.py`, `test_internal_error.py`, `test_storage_foundation.py`, `test_openapi.py`, `test_health.py` |
| Provider boundary | a `Mock()` Dropbox client that returns or raises real Dropbox SDK objects | We call Dropbox correctly and turn every Dropbox error into our error | `test_dropbox_*.py`, `test_dependencies.py` |
| Real provider | real Dropbox | Our assumptions about Dropbox actually hold | `tests/integration/` |

Tests check what a caller can observe (status, body, stored bytes), not private helpers. The exceptions are checks that establish a requirement: "storage was never called" for rejected input, and "the token is not in the log".

## What we test and why

### Path validation (every route)

- **Contract:** every route that takes a path returns `400 invalid_request` for a bad path and never calls storage.
- **Cases:** valid paths (root file, nested, dots in the name, spaces) are returned unchanged. Rejected: missing, empty, no leading `/`, trailing `/`, root `/`, empty segment `//`, `.` and `..` segments, newline, null byte, tab, DEL.
- **How:** `test_validation.py` checks the function directly, then sends every bad path to every route (upload, metadata, download, both paths of a move, delete) with a storage that fails the test if it is called.
- **Why:** before the shared validator, download had its own weaker check and let `/docs/../report.pdf` through to Dropbox.

### Create: `POST /files`

- **Contract:** `201` and the file's metadata; never overwrites; 150 MB limit.
- **Cases:** normal file, empty file, same bytes come back, missing `file` or `path`, bad path, file over the limit (including when the size is unknown up front), second upload to the same path returns `409` and the first file is unchanged, each storage error.
- **Live:** upload a real file, read it back, delete it.

### Read: `GET /files/metadata` and `GET /files/download`

- **Contract:** metadata returns a `FileResource`; download returns the exact bytes. A missing file is `404`; a folder is `400`. Reading changes nothing.
- **Cases:** success, missing file, missing or bad path, metadata does not change storage, empty file, special characters, spaces, long and nested paths, `Content-Disposition` encoding of quotes and non-ASCII names, each storage error, a Dropbox timeout becomes `502`.
- **Live:** read metadata of a real file, a missing path returns `404`, downloading a real folder returns `400`.

### Update: `PATCH /files` (rename or move)

- **Contract:** `200` with the new metadata, same `id` and bytes, old path gone. Never overwrites: something at `new_path` gives `409` and nothing moves.
- **Request:** source is the `path` query parameter; destination is the `new_path` JSON body field. The `from_path`/`to_path` form remains accepted as a compatibility alias.
- **Cases:** both request naming forms, move, content kept and old path gone, case-only rename refused, repeating a move returns `404`, missing file, move onto an existing file refused, invalid input never touches storage, badly typed body uses our error shape, each storage error. The mocked Dropbox tests check source errors are reported against the source and destination paths.
- **Live:** move into a new subfolder, check the id and bytes, repeat returns `404`, move onto an existing file returns `409`.

### Delete: `DELETE /files`

- **Contract:** `204`, then the file is gone. Deleting again returns `404`. Folders are refused with `400`, because Dropbox would delete everything inside.
- **Cases:** delete, deleted file cannot be fetched, same path twice, missing file, missing or bad path, each storage error, folder refused, rate limit.
- **Live:** delete a real file, check it is gone, repeat returns `404`, real folder refused.

### Error shape (every route)

- **Contract:** every error is exactly `{"error": {"code": "...", "message": "..."}}`.
- **Cases:** `test_error_style.py` sends one bad request of each kind to each route: unknown URL (`404 not_found`), wrong method (`405 method_not_allowed`), body that is not JSON, wrongly typed fields, our own path checks, missing files, upload conflict, and an unexpected bug in our code (`500 internal_error`). `test_internal_error.py` checks the catch-all logs the failure without hiding our expected errors. `test_storage_foundation.py` checks each of our exceptions maps to its status and code. `test_openapi.py` checks Swagger lists the same error responses.

### Dropbox error mapping and logging

- **Contract:** no Dropbox exception or SDK object reaches the caller. Each Dropbox failure becomes one of our errors and writes one log line with the operation, our error, the Dropbox error and the request id. File paths, tokens, file contents and Dropbox's free-text messages are never logged.
- **Cases:** lookup and write errors, conflict, auth failure (token not in the log), outage (logged at `ERROR`, no stack trace, no response body), move failure (no paths in the log), our own refusals and successful calls are not logged.

### Configuration and the shared client

- **Contract:** the refresh token is preferred over an access token; missing credentials give `503 provider_not_configured`; one Dropbox client is shared by all requests.
- **Cases:** refresh token used, refresh token without app key/secret refused, access-token fallback, no credentials, client created once, missing credentials are not cached (fixing `.env` works without a restart).

## Showing a test catches a real defect

`test_every_route_rejects_bad_path_before_storage` was run against the download route as it was before the shared validator. It failed for all seven bad paths, for example:

```
Failed: storage.download was called with ('/docs/../report.pdf',)
```

With the shared validator it passes. Likewise, 7 tests in `test_error_style.py` fail against the `main.py` from before the 404/405 handler, because FastAPI returned `{"detail": "Not Found"}`.

## Shared conformance suite

The vertical's shared conformance suite (55 HTTP tests, [ospsd26-cloud-storage PR #6](https://github.com/Dayana20/ospsd26-cloud-storage/pull/6) at `b77617c`) checks that Teams 1, 3 and 6 behave the same. It only uses HTTP, so it runs against our app with real Dropbox. Each test works in its own `/conformance-<random>` folder and deletes it at the end.

**In CI:** the `conformance` job in `.github/workflows/ci.yml` runs on every push to `hw2-milestone3`. It starts the app with the Dropbox credentials from the repository secrets (`DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`), then runs the suite in two steps:

- **Agreed rules** (`-m "not proposed"`): must pass, or the job fails.
- **Proposed rules** (`-m "proposed"`): rules not yet agreed between the teams. Reported, but they don't fail the job.

The run's summary page shows the counts, and the JUnit files and service log are uploaded as the `conformance-results` artifact.

**Locally:** start the app in one terminal and the suite in another:

```bash
# terminal 1, in this repo
uvicorn app.main:app --port 8011 --no-access-log

# terminal 2, in a clone of ospsd26-cloud-storage with PR #6 checked out
CONFORMANCE_BASE_URL=http://127.0.0.1:8011 python -m pytest conformance/tests -o addopts="--import-mode=importlib" -q
```

**Recorded run, Nov 11, 2026 (Shini), `hw2-milestone3` at `4530d43`, real Dropbox: 51 of 55 pass.**

| Rules | Passed | Failed |
| --- | --- | --- |
| Agreed | 25 | 0 |
| Proposed | 26 | 4 |

Earlier the same day, at `27460b6`, it was 45/55: `/health/provider` was missing and move used `from_path`/`to_path` instead of the shared `path`/`new_path`. #42 fixed both.

The 4 failures are all proposed rules:

| Test | Expected | We return |
| --- | --- | --- |
| `test_errors.py::test_unknown_route` | `404 route_not_found` | `404 not_found` |
| `test_move.py::test_move_same_path[same]` | `422 invalid_operation` | `400 invalid_request` |
| `test_move.py::test_move_same_path[case-only]` | `422 invalid_operation` | `400 invalid_request` |
| `test_move.py::test_move_folder` | `422 invalid_operation` | `400 invalid_request` |

The suite does not cover the upload size limit, provider errors (403, 502, 503), empty folders, lists longer than one page, or letter case; our own tests above cover those.

## What the fake assumes

`FakeDocumentStorage` (`tests/fakes.py`) only needs enough behaviour for the route tests. It differs from Dropbox in ways that matter:

- **Paths are case-sensitive in the fake, case-insensitive in Dropbox.** The fake would accept `/A.txt` next to `/a.txt`; Dropbox returns `409`. Case behaviour is only checked by the route's own case-only-rename rule and the live tests.
- **The fake has no folders,** so "folder refused" is tested only in the mocked Dropbox tests and the live delete test.
- **The fake's `id` is the path,** so the "id survives a move" guarantee is only really checked by the live move test.

## Gaps and known limitations

- **Network failures are not logged.** A timeout or connection error becomes `502 provider_error`, but the Dropbox error logger only logs Dropbox SDK exceptions, so these leave no log line. A timeout is only tested for metadata.
- **Uncertain writes are not tested.** If an upload times out after Dropbox saved the file, the caller gets `502`, and retrying gets `409`. That outcome is not simulated in a test or documented as a retry rule yet.
- **`Allow` header on 405 is incomplete for `/files`:** it lists only `POST`, because upload, move and delete are separate routers. Behaviour of FastAPI, not changed.
- **No concurrency tests.** Two clients moving or uploading the same path at once rely on Dropbox's own conflict handling.
- **No coverage target.** The behaviours above are what the tests establish; we have not measured line coverage.
