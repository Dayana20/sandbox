# DESIGN: Document Storage Agent (Dropbox) adopting the shared Document Storage API

| | |
| --- | --- |
| **Title** | Team 1 (Dropbox) adopts the shared Document Storage API |
| **Authors** | TODO |
| **Team / vertical** | Team 1, Document Storage |
| **Internal reviewer** | Annie, Shini |
| **External reviewer** (contract-facing parts: sections 3 and 6) | Darsh (Team 6) |
| **Status** | Draft |
| **Last updated** | Nov 3, 2026 |
| **Decision memo** | https://docs.google.com/document/d/1K9U8uO-FVbeu0PGlWpr_frJ6YQmoHXdz/edit |
| **Shared contract** | [Dayana20/ospsd26-cloud-storage](https://github.com/Dayana20/ospsd26-cloud-storage) tag `0.1.0`, commit `7c847b0` (repository baseline; route and error details follow the Oct 28 memo until they land in the package) |
| **Implementation work** | [#31](https://github.com/Dayana20/sandbox/pull/31) |

---

## 1. Context, goals, non-goals

### Context

A consumer wants to upload, read, move, list and delete documents without caring which service stores them. Today the three Document Storage services differ in ways a caller must handle, and some differences cause silent data loss.

### Non-goals

- **Moving files between providers.** A path or id refers to a file in Team 1's Dropbox app folder only. Switching to another team's service does not bring the files along (shared memo, "What we are not doing").
- **Choosing a bucket or app folder in requests.** Each deployment serves one Dropbox app folder, set by its credentials in `.env`. A consumer switches storage by changing the base URL and credentials (shared memo).
- **Putting our cache and idempotency into the shared contract.** Team 1's Redis metadata cache and `Idempotency-Key` uploads stay in Team 1 extensions. They keep working, but other teams don't have to implement them, and a consumer must not depend on them to use the shared API.

Concrete incompatibilities that affect Team 1:

| Behavior | Team 1 today | Another team today | What a caller must change or can lose |
| --- | --- | --- | --- |
| Replace an existing file | `POST /files` returns 409 and never overwrites | Team 3 overwrites when `overwrite=true`; Team 6 has `PUT /files/{key}` | A caller written for Team 3 expects overwrite to work and gets 409 here |
| Delete a folder | `DELETE /files` returns 400 for a folder | Team 3 deletes the folder and everything in it | A caller that relies on recursive delete leaves data behind on Team 1 |
| Path without leading `/` | `validate_path` returns 400 | Team 6 uses `docs/report.pdf` with no leading `/` | A path valid on one service is rejected on another |
| List | Not implemented | Teams 3 and 6 have list, with different response shapes | A caller cannot list at all against Team 1 |

### Goals (observable)

1. A consumer runs this workflow against Team 1 with the shared request shapes and no Team 1 specific code: create, metadata, download and compare bytes, list the folder, move, metadata at the new path, delete, metadata returns 404.
2. Team 1 passes the shared conformance suite in the contract repo.
3. Every existing HW1 route that is not in the common core still works, or its removal is recorded in section 6 with migration instructions.

---

## 2. Architecture and request flow

### Components that change

| Component | File | Responsibility | Change |
| --- | --- | --- | --- |
| Interface | `app/providers/base.py` (`DocumentStorage`) | The only type routes depend on | Add `replace`, `list`, `health`; extend `delete` to folders |
| Provider adapter | `app/providers/dropbox/storage.py` (`DropboxStorage`) | Calls Dropbox, returns `FileResource` | Implement the new methods |
| Error mapping | `app/providers/dropbox/error_mapping.py` | Dropbox exception to domain exception | Add mappings for replace and list |
| HTTP routes | `app/api/routes/` | Validate input, call storage, return result | Add `PUT /files`, `GET /files`, `GET /health/provider` |
| Path rules | `app/validation.py` | `validate_path` | Replace "reject missing leading `/`" with `clean_up_path` (Laya) |
| Error handlers | `app/main.py`, `app/errors.py` | Domain exception to `{"error": {"code", "message"}}` | Rename codes if the code table changes |
| Startup config | `app/dependencies.py` (`get_document_storage`) | Creates the Dropbox client from `.env` | No change. The Dropbox client is created once and shared by all requests (`get_dropbox_client()` uses `functools.cache`). If credentials are missing it isn't cached, so fixing `.env` and retrying works. |

**Dependency direction:** routes depend on `DocumentStorage`. Only `app/providers/dropbox/` and `app/dependencies.py` know Dropbox exists. This is unchanged from HW1.

**Who creates and closes the client:** `get_dropbox_client()` builds one Dropbox client from `.env` the first time a request needs it and caches it with `functools.cache`, so every request shares it. Nothing closes it explicitly; it lives as long as the process. If credentials are missing it isn't cached, so fixing `.env` and retrying works.

**State:** Team 1 keeps no application state; all file state lives in Dropbox. (With `REDIS_URL` set, Team 1's cache and idempotency records live in Redis. They are Team 1 extensions, outside the shared contract.)

### Request trace: success (`PUT /files`, replace)

1. Route parses form fields `file` and `path`.
2. `clean_up_path(path)` normalizes the path. Invalid path returns `400 invalid_request` and Dropbox is not called.
3. Route calls `storage.replace(path, content)` through `Depends(get_document_storage)`.
4. `DropboxStorage.replace` calls `files_get_metadata(path)` to read the current `rev`. (Dropbox call 1)
5. It calls `files_upload(content, path, mode=WriteMode.update(rev))`. (Dropbox call 2)
6. `to_file_resource()` converts the result to `FileResource`.
7. Route returns `200` with the file info JSON.

**Logging:** no log line on success. Every response carries an `X-Request-ID` header.

### Request trace: expected failure (`PUT /files` on a missing path)

1. Steps 1 to 3 as above.
2. `files_get_metadata` raises `ApiError` with a not-found lookup error.
3. `translate_lookup_error` raises `FileNotFoundError`. The `@logs_dropbox_errors` decorator writes one `dropbox_error` line with the operation, the error type, Dropbox's error and Dropbox's request id. No file path is logged. `app/main.py` then writes `request_failed operation=… error=not_found status=404 provider=yes request_id=…`.
4. `app/main.py` returns `404 {"error": {"code": "not_found", "message": "..."}}`.
5. Nothing is created. Create and replace never overlap.

---

## 3. API and data model

### Route table

| Operation | Shared route | Team 1 today | Change needed |
| --- | --- | --- | --- |
| Health (API) | `GET /health` | `GET /health` exists | None |
| Health (provider) | `GET /health/provider` | Missing | New (issue #2, Dayana) |
| Create | `POST /files` (form: `file`, `path`) | Same | Rename error codes only, if needed |
| Replace | `PUT /files` (form: `file`, `path`) | Missing | Done for Milestone 2; review and merge |
| Download | TODO final route (open question 2) | `GET /files/download?path=` | None if this route is agreed |
| Metadata | TODO final route (open question 2) | `GET /files/metadata?path=` | Likely none |
| Move | `PATCH /files?path=` with `{"new_path"}` | Same route; returns `400` for a same-path move, case-only rename or folder | Change those cases to `422 invalid_operation` if #5 is accepted |
| Delete | `DELETE /files?path=` | Files only, 400 for folders | Recursive folder delete |
| List | `GET /files?path=` | Missing | New (Yashwanth, issue #3) |

### File info object

`id`, `name`, `path`, `size`, `modified_at`. Team 1's `FileResource` already has these fields. `list` adds a `type` field (`file` or `folder`), pending open question 4.

VERIFY: `modified_at` is returned today without a timezone (`2026-10-05T14:30:00`). The memo proposes UTC with a trailing `Z`. State what Team 1 will return and who confirms it.

### Representative request and response (observed response)

```
PUT /files
Content-Type: multipart/form-data
file=<bytes>, path=/docs/report.pdf

200 OK
{
  "id": "id:QqRAUO3-OU4AAAAAAAAAVA",
  "name": "report.pdf",
  "path": "/docs/report.pdf",
  "size": 22,
  "modified_at": "2026-11-04T16:35:07"
}
```

Observed Nov 4, 2026 against real Dropbox through the app (path shortened). Procedure: `tests/integration/test_replace_dropbox.py`. A missing path returned `404 not_found` and nothing was created. Note: `modified_at` has no timezone today, so the UTC `Z` from the memo isn't implemented yet.

### Information loss and limits

- **Letter case:** Dropbox treats paths differing only in case as one file. Case-only rename returns 400 today.
- **Upload limit:** README says 150 MB, the memo says 150 MiB. VERIFY against `app/api/routes/` and the Dropbox docs, then state the exact byte limit. The status above the limit is 400 today; 413 is open (open question 9).
- `id` is a Dropbox id and is opaque to callers.

---

## 4. Alternatives and tradeoffs

### Decision 1: implement replace with `WriteMode.update(rev)`

| | Chosen: read rev, then `update(rev)` | Alternative: `WriteMode.overwrite` |
| --- | --- | --- |
| Dropbox calls | 2 | 1 |
| Concurrent edit between read and write | Dropbox refuses the write | Silently replaces the other change |
| Missing file | `files_get_metadata` raises not-found, so we return 404 and create nothing | Would create the file, so replace and create overlap |
| Consumer impact | Needs a status for "someone else changed it" (open question 3: 409 or 422) | None |

### Decision 2: keep existing routes

Team 1's `/files/metadata`, `/files/download` and `PATCH /files` already match the memo. This is being kept as is.

**Alternative:** move to Team 6's key-in-URL routes (`/files/{key}`). We kept `?path=` because Teams 1 and 3 already share these routes, so only one team changes instead of two, and a path containing `/` doesn't need URL encoding inside a route segment. **Revisit** if the contract adopts key-in-URL routes.

### Decision 3: normalize paths versus reject

Normalization (`clean_up_path`) to allow users to find a path without using an absolute path.

**Alternative:** keep rejecting paths without a leading `/` (HW1 behavior). Normalizing lets a Team 6-style path (`docs/report.pdf`) work on Team 1 too. **Cost:** the returned `path` can differ from what the caller sent (we return `/docs/report.pdf`), so callers must use the path in the response. **Revisit** if the contract requires paths to be returned exactly as sent.

---

## 5. Failure behavior and operations

### Error translation

| Dropbox outcome | Domain exception | HTTP | Code |
| --- | --- | --- | --- |
| Path not found | `FileNotFoundError` | 404 | `not_found` |
| Path already exists | `FileConflictError` | 409 (open question 3) | `conflict` |
| Malformed path or name | `InvalidRequestError` | 400 | `invalid_request` (rename to `invalid_input`) |
| No permission | `PermissionDeniedError` | 403 | `permission_denied` |
| Dropbox failure or rate limit | `ProviderError` | 502 | `provider_error` (rename to `provider_failure`) |
| Provider not configured | `StorageNotConfiguredError` | 503 | `provider_not_configured` |
| File too large | `InvalidRequestError` today | 400 today, 413 open | `invalid_input` |

### Uncertain writes and retries

- After a 502 or 503 on create, replace, move or delete, the outcome is unknown. The caller checks metadata before retrying.
- **Folder delete:** Dropbox may fail after deleting part of a folder. The contract returns 502 and the caller lists the folder. Dropbox's `files_delete_v2` deletes a folder in one call. How it fails on a very large folder is not yet verified. Per Dropbox's docs it can refuse with a "too many files" error.
- **Retries:** Team 1 never retries an operation automatically. After a 502 or 503 the write may already have happened, so a blind retry could create a duplicate, overwrite a newer change, or delete a file the caller has since re-created. The caller decides, after checking metadata.

### Configuration and credentials

- `.env` holds `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN` (optional `DROPBOX_ACCESS_TOKEN`). `.env` is not committed.
- The app starts without credentials; they are read when a file route needs Dropbox.
- **Logging:** on a Dropbox failure, one `dropbox_error` line (operation, error type, Dropbox's error, Dropbox request id) and one `request_failed` line (operation, error code, status, provider involved, `X-Request-ID`). Tokens, file paths, file contents and Dropbox's free-text messages are never logged. uvicorn's own access log does print URLs, so deployment runs with `--no-access-log`.

### Cost of each affected operation

| Operation | Local work | Dropbox calls |
| --- | --- | --- |
| Create | Validate path, read upload | 1 (`files_upload`) |
| Replace | Validate path, read upload | 2 (`files_get_metadata`, `files_upload`) |
| Move | Validate two paths | 2 (`files_get_metadata`, `files_move_v2`) |
| Delete (file) | Validate path | 2 (`files_get_metadata`, `files_delete_v2`) |
| List | Sort by path | 1 `files_list_folder`, plus 1 `files_list_folder_continue` per extra page |
| Provider health | None | 1 (`health_provide`) |

**Deployment (Milestone 3):** hosting is not decided yet (owner: **[name]**, decide by Nov 7). Assumptions so far: credentials come from environment variables, never from the image; Redis is optional; one Dropbox app folder per deployment.

---

## 6. Migration and coordination plan

**Contract revision adopted:** tag `0.1.0` (commit `7c847b0`), the template baseline. Routes and errors follow the memo until the storage package is tagged.

### What changes

| Area | Change | Compatibility effect on existing callers |
| --- | --- | --- |
| Routes | Add `PUT /files`, `GET /files`, `GET /health/provider` | None (additive) |
| Delete | Folders are deleted recursively instead of returning 400 | A caller that relied on the 400 now deletes data. Record in release notes. |
| Paths | Leading `/` is added instead of rejected | A request that returned 400 now succeeds |
| Errors | Pending issue #4 (Darsh) | If renamed, callers branching on `invalid_request` or `provider_error` must switch to `invalid_input` / `provider_failure`. Listed in release notes. |
| Python | README says 3.10; the memo says 3.12 | Update `.python-version`, CI and `requirements.txt` |
| Tests | Add tests for each new route; update `test_validation.py` and `test_delete.py` | None |
| Docs | Update the README and add new route sections | None |

### Work breakdown

| PR | Owner | Depends on | Verification |
| --- | --- | --- | --- |
| `clean_up_path` and updated validation | Laya | Path rule (open question 1) | Updated `test_validation.py` |
| `PUT /files` replace | Annie, Shini | Open question 3 for the conflict status | Fake-storage tests, mocked Dropbox tests, one integration test |
| `GET /files` list | Yashwanth | Path rule, open questions 4 and 5 | Same three levels, including a folder with more than one Dropbox page |
| `GET /health/provider` | Dayana | None | Test with the fake and with bad credentials |
| Recursive folder delete | Laya | Open question 6 | Integration test with a nested folder |
| Error code rename | Yashwanth | Code table decision | Updated `test_storage_foundation.py` |
| Python 3.12 and package adoption | Annie | Package skeleton | CI green |

### If the contract changes after implementation starts

The coordinator announces the change in the document-storage Slack channel. Per the memo, a breaking change needs a new tag and sign-off from all three implementation contacts (Yashwanth for Team 1). Team 1 pins to a tag, not a branch, so a change reaches us only when we adopt the new tag.

---

## 7. Testing

### Guarantees mapped to checks

| Guarantee | Check | Level |
| --- | --- | --- |
| Create never overwrites | `test_upload.py`; `integration/test_upload_dropbox.py` | Fake, mocked Dropbox, live Dropbox |
| Replace never creates | `tests/test_replace.py` (fake), `tests/integration/test_replace_dropbox.py` (live) | Fake, live |
| Replace refuses a stale write | Planned: mocked Dropbox that raises a conflict on `WriteMode.update(rev)`, plus one live test that changes the file between the read and the upload (Milestone 3) | Live Dropbox |
| Move never overwrites | `test_update.py`; `integration/test_update_dropbox.py` | Fake, live |
| Delete removes a folder and its contents | Planned: update `tests/test_delete.py`, plus an integration test with a nested folder | Fake, live |
| List returns every page, sorted by path | Planned: `tests/test_list.py` with a mocked `has_more=True` response, plus a live folder with more than one page | Mocked Dropbox with `has_more`, live |
| Bad paths return 400 and never reach Dropbox | `test_validation.py` (update for normalization) | Fake |
| Error body shape and codes | `test_storage_foundation.py` | Fake |
| Dropbox failures are logged without secrets | `test_dropbox_error_logging.py` | Mocked Dropbox |

Fast tests (`pytest`) need no credentials. Live tests (`pytest tests/integration -v`) need a Dropbox token, write under `/integration-tests/`, and delete what they create.

### Consumer workflow (same logic for every service)

Upload a file, read its metadata, download it and compare bytes, list its folder, move it, read metadata at the new path, delete it, confirm metadata returns 404.

**Conformance suite:** Team 6 owns the shared suite in the contract repo. Team 1 will run it against its service with its base URL and Dropbox credentials. Fixtures create files under `/integration-tests/<random id>/` and delete that folder at the end, even when a test fails. Example of a failing check that reveals a mismatch: replace on a missing path must return `404`. If our service created the file instead, that test fails.

---

## 8. Open questions and review

### Open questions

| # | Question | Consequence for Team 1 | Owner | Next step |
| --- | --- | --- | --- | --- |
| 1 | Path rule (leading `/`, max length) | `clean_up_path` behavior; we must confirm our length limit | Laya | Write the rule into the contract |
| 3 | 409 or 422 for an existing destination | Changes create, replace and move statuses | Darsh (Team 6) | Confirm with Teams 1 and 3 |
| 4 | How list marks folders | Shape of list entries | Yashwanth, Jing | Add `type` field or exclude folders |
| 5 | Size of a full list | Number of Dropbox calls per list | Yashwanth | Decide cap or optional cursor |
| 6 | Folder delete that fails partway | Status and caller guidance | All teams | Decide status |
| 9 | Smallest accepted upload and the status above it | Our 150 MB or MiB limit | Teams 1 and 3 | Confirm units and status |
| 11 | Versioning and approvals | Which commit we pin | Coordinator | Define the first tag |
| 12 | Routes for download, metadata and delete | Whether our current routes change | Clause owners | Name routes in the contract draft |
| 13 | One error code name per status | Rename `invalid_request` / `provider_error` or not | Darsh (#4) | Teams 1 and 3 confirm on #4 |

### Review log

| Reviewer | Comment | Response | Outcome |
| --- | --- | --- | --- |
| TODO | | | Changed / Explained / Accepted risk / Deferred (owner, date) |

---

## 9. Actions

| Task | Owner | Output | Depends on | Target |
| --- | --- | --- | --- | --- |
| Internal review | TODO | PR comments | Draft complete | Mon Nov 2 evening |
| External review of sections 3 and 6 | TODO (Team 3 or 6 contact) | PR comments | Draft complete | Tue Nov 3 |
