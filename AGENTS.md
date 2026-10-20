# AGENTS.md

Guide for anyone (teammate or AI coding tool) changing this repo. Setup and endpoint docs are in [README.md](README.md).

## What this service is

A FastAPI service for storing documents. Callers upload, read, move and delete files. Dropbox is the provider, but the app only talks to Dropbox through one interface.

## Code map

- `app/main.py` - creates the FastAPI app and turns our errors into JSON responses
- `app/api/router.py` - includes every route module
- `app/api/routes/` - one file per feature: `upload.py`, `read.py`, `update.py`, `delete.py`, `health.py`
- `app/providers/base.py` - `DocumentStorage`, the interface routes depend on
- `app/providers/dropbox/` - the Dropbox implementation:
  - `client.py` creates the Dropbox SDK client from `.env`, preferring the refresh token over a short-lived access token
  - `storage.py` has `DropboxStorage`, one method per operation
  - `error_mapping.py` turns Dropbox errors into our errors and logs the original Dropbox error (`@logs_dropbox_errors`)
- `app/dependencies.py` - `get_document_storage()`, which hands a `DropboxStorage` to the routes. The Dropbox client is created once and shared (`get_dropbox_client()`)
- `app/validation.py` - `validate_path()`, the path check every route uses
- `app/errors.py` - our errors (`FileNotFoundError`, `FileConflictError`, `InvalidRequestError`, `PermissionDeniedError`, `ProviderError`)
- `app/models/file.py` - `FileResource`, the response returned by file endpoints
- `tests/fakes.py` - `FakeDocumentStorage`, an in-memory stand-in for Dropbox
- `tests/integration/` - tests that call real Dropbox

## Rules

- Routes only use `DocumentStorage`. They never import `dropbox` or `DropboxStorage`.
- Routes check every path with `validate_path` from `app/validation.py` before calling storage. Don't write a route-specific path check.
- Routes get storage with `Depends(get_document_storage)`. Don't create a Dropbox client inside a route.
- Only code in `app/providers/dropbox/` calls the Dropbox SDK.
- Dropbox errors must be turned into `app/errors.py` errors before they leave `DropboxStorage`, raised `from` the Dropbox exception. Put `@logs_dropbox_errors` on every `DropboxStorage` method.
- Never log file paths, tokens, file contents or Dropbox's free-text messages.
- File endpoints return `FileResource`, never raw Dropbox objects.
- Don't overwrite or auto-rename files. Uploads and moves onto an existing path return `409`.
- Never commit `.env`, tokens or keys.

## Commands

    pip install -r requirements.txt
    uvicorn app.main:app --reload       # API at http://127.0.0.1:8000/docs
    pytest                              # fast tests, no Dropbox needed
    pytest tests/integration -v         # real Dropbox, needs .env
    ruff check .                        # lint
    mypy app                            # type check

## Tests

- Route tests replace Dropbox with `FakeDocumentStorage` using `app.dependency_overrides[get_document_storage]`.
- `DropboxStorage` is tested with a mocked Dropbox client, so no network is needed.
- Integration tests skip themselves when no Dropbox credentials are set, write under `/integration-tests/`, and delete what they create.

## Adding an endpoint

1. Add the method to `DocumentStorage` in `app/providers/base.py` if it is new.
2. Implement it in `DropboxStorage` and `FakeDocumentStorage`.
3. Add a route file in `app/api/routes/` and include it in `app/api/router.py`. List the errors it can return with `responses=error_responses(...)` from `app/api/responses.py`, so `/docs` matches the README.
4. Add route tests, a mocked Dropbox test and an integration test.
5. Document the endpoint in README.md.

## Contributing

- Branch off `milestone-3`, open a PR into `milestone-3`. Don't push to it directly. Don't merge anything into `main`, `yashwanth` or the `milestone-*-base` branches; they hold the submitted milestones.
- A teammate reviews and someone other than the author merges.
- Keep each PR to one feature. Don't mix in unrelated changes.
- `pytest`, `ruff check .` and `mypy app` must pass before merging. CI runs all three.
- Say in the PR description if you used AI help.
