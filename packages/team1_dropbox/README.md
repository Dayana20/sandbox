# Team 1 Dropbox Storage

`team1-dropbox-storage` is Team 1's standalone Dropbox implementation of the
shared `cloud-storage-api` `DocumentStorage` contract. It is a normal Python
package: using it does not start or import FastAPI, Redis, Nginx, Docker, or the
deployed Team 1 service.

The package uses the distinct `team1_dropbox` import namespace, so it can be
installed in an application that already has its own top-level `app` package.

## Compatibility

- Shared contract Git tag: **`0.3.1`**
- Package version: **`0.1.0`**
- Python: **3.12 or later**
- Dropbox SDK: **12.1.0**

The provider code is intentionally self-contained under `team1_dropbox`. It
adapts the stable behavior of the deployed service rather than importing or
refactoring the service's generic `app` package. This creates a small amount of
provider-code duplication, but keeps the deployed FastAPI application isolated
from package consumers.

## Installation from GitHub

Install the package directly from this repository and package subdirectory:

```bash
python -m pip install "team1-dropbox-storage @ git+https://github.com/Dayana20/sandbox.git@hw3-dropbox-package#subdirectory=packages/team1_dropbox"
```

For a reproducible production integration, replace `hw3-dropbox-package` with
the reviewed commit SHA supplied by Team 1 after the PR is finalized.

The public import is:

```python
from team1_dropbox import Team1DropboxStorage
```

## Dropbox test-account setup

Create a Dropbox app owned by Team 5 and connect it to a disposable test
account. Do not reuse Team 1's application or credentials.

Enable these scoped permissions in the Dropbox App Console:

- `account_info.read` for `check_health()`
- `files.metadata.read` for metadata and folder listing
- `files.content.read` for downloads
- `files.content.write` for create, replace, move, and delete

Choose App Folder access when the integration should be confined to the app's
folder, or Full Dropbox access only when the test account requires it. Complete
Dropbox's OAuth authorization flow with offline access to obtain a refresh
token. Keep the app key, app secret, and refresh token in the consuming
application's secret store; never commit them.

Set the following variables in Team 5's process environment:

```dotenv
DROPBOX_APP_KEY=
DROPBOX_APP_SECRET=
DROPBOX_REFRESH_TOKEN=
```

The package does not search for or load a particular `.env` file. Team 5 may
use its own configuration framework to populate the environment.

## Initialization

Environment-based initialization is the shortest option:

```python
from cloud_storage_api.interface import DocumentStorage
from team1_dropbox import Team1DropboxStorage

storage = Team1DropboxStorage.from_env()
assert isinstance(storage, DocumentStorage)
```

Credentials can instead be supplied explicitly:

```python
storage = Team1DropboxStorage(
    app_key="...",
    app_secret="...",
    refresh_token="...",
)
```

For tests or applications that already manage a Dropbox SDK client, inject it
without setting environment variables:

```python
import dropbox

client = dropbox.Dropbox(
    oauth2_refresh_token="...",
    app_key="...",
    app_secret="...",
)
storage = Team1DropboxStorage(client=client)
```

## Basic workflow

```python
from team1_dropbox import Team1DropboxStorage

storage = Team1DropboxStorage.from_env()

created = storage.create(
    "/team5-test/notes.md",
    b"# Integration Test",
)

content = storage.download("/team5-test/notes.md")
assert content == b"# Integration Test"

storage.delete("/team5-test/notes.md")
```

Creating never overwrites or auto-renames an existing file. Replacing reads
the current Dropbox revision and uses a conditional update, so a concurrent or
stale replacement raises a conflict instead of losing another write. Moving
also refuses to overwrite the destination.

## Metadata

Every metadata-returning operation produces the contract's actual `FileInfo`
dataclass, not a Dropbox SDK object or FastAPI model:

```python
FileInfo(
    id="id:example",
    name="notes.md",
    path="/team5-test/notes.md",
    size=18,
    modified_at="2026-11-17T17:30:00Z",
    etag="015abc123",
    type=None,
)
```

`list_files()` sets `type` to `"file"` or `"folder"`. Folder entries have
`size`, `modified_at`, and `etag` set to `None`. File timestamps are normalized
to UTC ISO 8601 strings ending in `Z`.

## Shared errors

All expected public failures use classes from `cloud_storage_api.errors`:

- `InvalidRequestError` for missing configuration or malformed paths
- `NotFoundError` when a path does not exist
- `ConflictError` for occupied destinations or stale replacements
- `PermissionDeniedError` when Dropbox rejects credentials or permissions
- `InvalidOperationError` when a file-only operation receives a folder (or vice versa)
- `ProviderError` for other provider failures
- `ProviderUnavailableError` for timeouts, connectivity failures, internal
  Dropbox outages, or a failed health check

Error messages never include credentials, file contents, or Dropbox's
free-text response messages.

## Supported contract operations

`Team1DropboxStorage` implements `create`, `replace`, `download`,
`get_metadata`, `list_files`, `move`, `delete`, and `check_health` with the
exact `0.3.1` signatures. It inherits the contract's default `open_download`,
`create_stream`, and `replace_stream` implementations.

Listing fetches every Dropbox page, returns direct children only, and sorts
the final results by path. `/` is accepted only by `list_files`; destructive
operations reject the root path.

## Tests and build

From the repository root:

```bash
python -m pip install -e "packages/team1_dropbox[test]"
python -m pytest -c packages/team1_dropbox/pyproject.toml packages/team1_dropbox/tests -m "not integration"
python -m ruff check packages/team1_dropbox
python -m mypy --config-file packages/team1_dropbox/pyproject.toml packages/team1_dropbox/src/team1_dropbox
python -m build packages/team1_dropbox
```

The real Dropbox test is opt-in and writes only under a unique
`/team1-package-integration/` path. Configure a disposable test account, then
run:

```bash
python -m pytest -c packages/team1_dropbox/pyproject.toml packages/team1_dropbox/tests/integration -m integration -v
```

The test creates a Markdown file, verifies the exact downloaded bytes, and
deletes the file in cleanup. It skips when any required credential is absent.

## Limitations

- The contract's default streaming methods buffer the entire object in memory.
  `open_download()` also makes separate metadata and download calls. The
  package intentionally uses these `0.3.1` defaults for compatibility.
- Byte-based create and replace use Dropbox's single-call upload endpoint and
  are therefore intended for files within that endpoint's size limit.
- The package does not create parent folders explicitly. Dropbox creates the
  file only when its destination path is valid for the configured account.
- No live Dropbox data is touched by the normal unit test suite. Live behavior
  requires the explicit opt-in integration credentials described above.
