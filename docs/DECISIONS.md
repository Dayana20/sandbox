# Engineering decisions

Why the service behaves the way it does, for reviewers and future maintainers. Each entry gives the choice, the alternatives we considered, and what it costs us.

## 1. A write to an existing path returns `409 conflict` instead of overwriting

**Decision:** `POST /files` (upload) and `PATCH /files` (move) never replace an existing file. If something is already at the target path, the request fails with `409 conflict` and both files are left unchanged.

**Context:** Dropbox lets the caller choose how a clash is handled: overwrite the file, auto-rename the new one (`report (1).pdf`), or fail. And by default, uploading the exact same contents to an existing path "succeeds" without writing anything, so the caller can't tell the file was already there.

**Options considered:**

| Option | What the caller gets | Problem |
| --- | --- | --- |
| Overwrite | Their file replaces the old one | Silent data loss. Two people uploading `report.pdf` at the same time means one loses their file and never finds out |
| Auto-rename | `201`, but stored as `report (1).pdf` | The file isn't at the path the caller asked for. They'd have to read the response to notice |
| **Fail with `409`** | A clear error naming the path | The caller has to choose: delete first, or pick another name |

**Why:** a storage service must never destroy data the caller didn't ask it to destroy. A `409` is easy to handle and impossible to miss. Overwriting is also easy to build on top later (delete, then upload), but lost data can't be recovered.

**How:** uploads use `WriteMode.add`, `autorename=False` and `strict_conflict=True`. Without `strict_conflict`, Dropbox quietly accepts an upload whose contents are identical to the existing file. Moves use `files_move_v2(autorename=False)`.

**Cost:**
- There's no "replace" operation. Updating a file's contents means `DELETE` then `POST`. Conditional updates (`PUT` with a revision) are the planned way to add safe replacing.
- Retries need care. If an upload times out after Dropbox has already saved the file, the caller gets `502`, and retrying the same upload then gets `409`. So the README tells callers to check whether the file is already there (`GET /files/metadata`) before retrying an upload, move or delete. This case isn't covered by a test yet (see the known gaps in `TESTING.md`).

**Evidence:**
- `test_upload_same_path_twice` (fake storage): a second upload returns `409` and `download` still returns the **first** file's bytes.
- `test_dropbox_upload_success` (mocked Dropbox) checks the exact call: `WriteMode.add`, `autorename=False`, `strict_conflict=True`. Removing any of them would fail this test.
- `tests/integration/test_upload_dropbox.py` (real Dropbox): uploading to the same path again returns `409`.
- Moves: `test_move_onto_existing_file_is_refused` (`409`, and neither file changes) and `test_dropbox_move_conflict_names_destination`. Tutorial step 5 shows a move onto an existing file refused with `409` and both files unchanged.
- Dropbox's documentation for `strict_conflict`: it "forces a conflict even when the target path refers to a file with identical contents". Without it, a repeat upload of the same bytes would quietly return success.

**What would make us revisit it:**
- **Callers need to replace files.** We'd add a conditional update (`PUT` with the file's current revision) rather than switching uploads to overwrite: the update succeeds only if nobody changed the file since the caller read it, and a stale update still gets `409`.
- **Retries after timeouts become common.** If clients regularly hit the "502, then 409 on retry" case above, the fix is idempotency keys, so a retried upload returns the original result instead of a conflict.

## 2. Operations on a folder are refused with `400`

**Decision:** metadata, download, move and delete only work on files. A folder path returns `400 invalid_request`.

**Context:** Dropbox's delete is recursive: deleting `/projects` removes everything inside it. One mistyped path could wipe a whole folder.

**Why:** the API is a document store, and every response is a `FileResource` describing one file. Refusing folders keeps a typo from causing mass deletion.

**Cost:** delete and move make **two** Dropbox calls instead of one: `files_get_metadata` to check the path is a file, then the real operation. There's also a tiny window where the path could change between the two calls, which we accept.

**Code and tests:** `test_dropbox_delete_refuses_folder`, `test_dropbox_move_refuses_folder`, `test_get_dropbox_metadata_refuses_folder`, and the live `test_delete_refuses_real_folder`.

## 3. Routes only know `DocumentStorage`, never Dropbox

**Decision:** routes call the `DocumentStorage` interface (`upload`, `get_metadata`, `download`, `move`, `delete`). Only `app/providers/dropbox/` imports the Dropbox SDK, and every Dropbox error is translated into one of our errors before it leaves that folder.

**Why:**
- **Testing:** route tests swap in an in-memory `FakeDocumentStorage`, so most of the suite runs in seconds with no network or credentials.
- **Stable API:** callers always get `{"error": {"code", "message"}}` with our codes, not Dropbox's error types.
- **Replaceable provider:** another backend means another class that implements the same five methods.

**Cost:** every new operation needs code in three places: the interface, the Dropbox class and the fake.

## 4. Dropbox login uses a refresh token

**Decision:** the client is built from `DROPBOX_REFRESH_TOKEN` plus the app key and secret. A short-lived `DROPBOX_ACCESS_TOKEN` is only a fallback.

**Context:** tokens generated in the Dropbox App Console expire after about 4 hours. Routes started failing mid-testing, and everyone had to generate a new token and edit `.env` again.

**Why:** a refresh token doesn't expire, and the SDK uses it to get new access tokens automatically. `scripts/get_refresh_token.py` makes getting one a one-time step.

**Cost:** setup needs the app key and secret as well as a token, and each person has to run the sign-in flow once.

## 5. Every error uses our shape, including FastAPI's own errors

**Decision:** missing or invalid input (a missing `path`, a wrong type, a body that isn't JSON) returns our `400 invalid_request` body, never FastAPI's default `422`. An unknown URL returns `404 not_found` and an unsupported method returns `405 method_not_allowed`, both in our shape instead of FastAPI's `{"detail": "..."}`.

**Why:** one error shape for every failure. A caller can handle `{"error": {"code", "message"}}` everywhere instead of parsing two formats. Optional parameters (`path: str | None = None`) let our own `validate_path` produce the message, and handlers in `app/main.py` convert FastAPI's validation, 404 and 405 errors to the same shape.

## 6. Unexpected bugs return `500 internal_error` with a fixed message

**Decision:** any exception the service doesn't expect returns `{"error": {"code": "internal_error", "message": "Internal server error"}}`. The real exception type is written to the server log with the request id, and the exception's text is never sent to the caller.

**Why:**
- **Same shape everywhere.** Without this, FastAPI returns a plain-text `Internal Server Error`, the one response a caller couldn't parse like the others.
- **Nothing leaks.** Exception text can contain file paths, Dropbox details or other internal information.

**Cost:** the caller learns nothing about what went wrong. They can quote the `X-Request-ID` from the response so we can find the log line.

## 7. Decisions from the sister-team review (PR #18)

- **One shared Dropbox client.** Creating a client per request meant a fresh access-token fetch on every request. The client is now created once and reused. If credentials are missing it isn't cached, so fixing `.env` and retrying works.
- **File paths are not logged.** File names can contain private information (`/hr/firing-alex.pdf`). A failure produces at most two log lines, and neither contains a path:
  - `request_failed`: the operation, error code, HTTP status, whether Dropbox was involved, and our request id, which is the same `X-Request-ID` the caller receives.
  - `dropbox_error` (only when Dropbox failed): Dropbox's typed error and Dropbox's own request id, for asking Dropbox support.

  Together these are enough to trace any failure without knowing which file it was. One exception sits outside our code: uvicorn's access log prints each request's URL, query string included. Production should run with `--no-access-log` (or a log filter) so paths don't reach the logs that way.
- **Control characters are rejected in paths.** Newlines or null bytes are never valid in a file name and could corrupt log lines.
