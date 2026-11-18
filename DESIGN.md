# DESIGN: Team 1 composes Storage, Calendar and Issue Tracker (HW3 Milestone 1)

> **⚠️ TBD** marks the few points the team has not decided yet. Everything else describes the code on `hw3-milestone1` (plus #48) as of Nov 18, 2026, or is labelled **Proposed**.

| | |
| --- | --- |
| **Title** | Team 1 composes Storage, Calendar and Issue Tracker behind one API operation |
| **Authors** | Shini Agarwal (document). Integration code by Dayana Alejandro (#46, #47, #48) and Yashwanth Kasanneni (#49, deployment) |
| **Team / vertical** | Team 1, Document Storage (Dropbox): Dayana Alejandro, Shini Agarwal, Annie Jain, Laya Mangalagiri, Yashwanth Kasanneni |
| **Internal reviewer** | ⚠️ TBD (a teammate who did not write this document) |
| **External reviewer** (contract-facing parts: sections 3, 6 and 7) | ⚠️ TBD (one reviewer from another team) |
| **Status** | Draft |
| **Last updated** | Nov 18, 2026 |
| **Shared contracts** | Storage: [ospsd26-cloud-storage](https://github.com/Dayana20/ospsd26-cloud-storage) `0.2.0` (service) and `0.3.1` (standalone package). Calendar: [OSPSD-Calendar](https://github.com/Airbus-A330/OSPSD-Calendar) `calendar-contract v0.1.0`. Issue Tracker: [OSPSD-Team-4](https://github.com/Tyler-Arciniaga/OSPSD-Team-4) `issue-tracker-contract-v1.1.0` |
| **Implementations used** | Storage: ours (Dropbox). Calendar: Team 5 [`team5-calendar-v0.1.0`](https://github.com/juno-junhyuk-lee/OSPSD-Team-5) (Google Calendar). Issue Tracker: Team 4 [`team-4-issue-tracker-trello-v1.0.0`](https://github.com/Tyler-Arciniaga/OSPSD-Team-4) (Trello) |
| **Decision memo** | HW2 storage memo, linked from [docs/DESIGN-HW2.md](docs/DESIGN-HW2.md) |
| **Implementation work** | #46 (Python 3.14), #47 (calendar), #48 (issue tracker), #49 (standalone Dropbox package), #50 (package request from Team 2) |

The HW2 design (how our service adopted the shared storage contract) is kept in [docs/DESIGN-HW2.md](docs/DESIGN-HW2.md).

---

## 1. Context, goals, non-goals

### Context

HW2 made each vertical a shared contract: storage (`cloud_storage_api`), calendar (`calendar_contract`) and issue tracking (`issue_tracker_contract`). In HW3 a consumer wants one request that does work in all three, for example "create a meeting, save its notes, open a follow-up issue", without writing code for each provider.

Per the TA, a team consumes another vertical by importing that team's **implementation package in-process**, not by calling their deployed HTTP API. Team 1's service therefore installs Team 5's calendar package and Team 4's Trello package and calls them through their contracts. We use our own implementation for storage.

What makes this hard, concretely:

| Difference | Storage (ours) | Calendar (Team 5) | Issue Tracker (Team 4) | What a caller could get wrong |
| --- | --- | --- | --- | --- |
| Error type | Our `StorageError` subclasses; HTTP body `{"error": {"code", "message"}}` | `CalendarError(code, message, retryable)` | `ServiceError(code, message, provider_involved)` | Three exception types and three code sets in one request |
| "Bad input" | `400 invalid_request` | `INVALID_INPUT` | `invalid_input`, which its contract maps to **422** | The same mistake surfaces as 400 from one step and 422 from another |
| Uncertain write | `502 provider_error`, check before retrying | `retryable` flag on the error | `provider_error` and `internal_error` are `OUTCOME_UNKNOWN_CODES` | A blind retry can create a second event or card |
| Identifiers | Path (`/docs/a.pdf`) plus an opaque Dropbox `id` | Opaque Google event `id` | Opaque Trello card `id` | Three id kinds to keep together to undo or look up a run |
| Time format | `modified_at` is UTC ending in `Z` | RFC 3339 with an **explicit offset**; times without one are rejected | none | A timestamp without an offset is refused by the calendar |

### Goals (observable)

1. One deployed API operation runs fixed steps across storage, calendar and issue tracker for one test account and returns the ids it created.
2. Every failure, from any step, uses our one error body and names the step. A write whose result is unknown is reported as unknown, never as "nothing happened".
3. Each partner implementation is replaced by configuration only (`CALENDAR_IMPL=fake|team5`, `TRACKER_IMPL=fake|team4`). The same operation runs unchanged against the in-memory fakes and the real providers.
4. Existing storage routes behave as in HW2 and keep passing the shared storage conformance suite in CI.

### Non-goals

- **A product, agent, user interface or user accounts.** Milestone 2 adds those. This milestone uses one test account per provider.
- **Calling other teams' deployed services over HTTP.** We import their packages, as the TA clarified.
- **Distributed transactions.** The three providers cannot commit together; we undo what we can and report what we cannot (section 5).
- **Every partner feature.** Only the operations the composed workflow needs are used: calendar `create` and `delete`, issue `create_issue` and `delete_issue`, storage `upload` and `delete`.

---

## 2. Architecture and request flow

### Components

| Component | File | Responsibility | Status |
| --- | --- | --- | --- |
| Shared contract packages | `cloud_storage_api`, `calendar_contract`, `issue_tracker_contract` (pinned in `requirements.txt`) | Types, interfaces and error codes we code against | Installed |
| Partner implementations | `team5_calendar`, `team_4_issue_tracker_trello` | Call Google Calendar and Trello | Installed |
| Calendar adapter | `app/integrations/calendar.py` | `get_calendar_service()` picks the implementation from `CALENDAR_IMPL`; `_MappedCalendarService` maps `CalendarError` codes to our errors; `InMemoryCalendarService` is the fake | Done (#47) |
| Issue tracker adapter | `app/integrations/issue_tracker.py` | `get_issue_provider()` picks from `TRACKER_IMPL`; `_MappedIssueProvider` maps `ServiceError` codes; `InMemoryIssueProvider` is the fake | Done (#48), but #48 was merged into `hw3-integrate-calendar-api` after #47 had merged, so it is **not on `hw3-milestone1` yet** |
| Storage | `app/providers/dropbox/`, `app/dependencies.py` | Unchanged from HW2 | Done |
| Composed operation | **Proposed:** `app/api/routes/workflows.py` | Runs the fixed steps, undoes earlier steps on failure, returns all ids | Not built |
| Error handling | `app/main.py`, `app/errors.py` | Domain errors to the HTTP error body | Done |
| Startup configuration | `app/core/config.py`, `.env` | `CALENDAR_IMPL`, `TEAM5_TOKEN_FILE`, `TRACKER_IMPL`, `TRELLO_*`, `DROPBOX_*` | Done |

**Dependency direction.** Routes depend only on our interfaces (`DocumentStorage` and the two `get_*` factories). Only the adapters import partner packages, and partner exceptions are translated inside them, so no partner type reaches a route.

**Who creates and closes clients, and who owns state.**
- **Dropbox:** one client, created on first use and cached (`get_dropbox_client()`), as in HW2.
- **Calendar:** `get_calendar_service()` builds a new service on each call. Team 5's service is bound to the OAuth token file in `TEAM5_TOKEN_FILE` and authorizes on its first call; each operation opens and closes its own Google API client (`build(...)` in a `with` block).
- **Issue tracker:** `get_issue_provider()` builds a new provider on each call. Team 4's provider reads `TRELLO_*` from the environment and opens one HTTP connection per request, so there is nothing to close.
- **Proposed:** the composed route gets both through FastAPI dependencies, built once per request, like storage today.
- **State:** Team 1 keeps no application state for this operation. Events live in the test account's primary Google Calendar, cards on one Trello list, documents in our Dropbox app folder.

### The composed operation

**Proposed** (⚠️ TBD: the team confirms or replaces it):

> `POST /workflows/meeting` with `{"title", "start", "end"}`:
> 1. **Calendar:** `create(CreateEvent(title, start, end))`.
> 2. **Storage:** `upload("/meetings/<event-id>.md", notes)`, where the notes file holds the title, times and event id.
> 3. **Issue tracker:** `create_issue("Follow up: <title>")`.
>
> Returns `201` with the event, the document's file info and the issue.

Guarantees it needs: each step runs at most once per request; a step runs only if the earlier ones succeeded; the response lists everything created, or names the failed step and what may be left behind.

Deliberate limits: one test account per provider; no retries inside the request; no update or delete operation across all three.

### Request trace: success (illustrative, for the proposed operation)

1. The route validates the body: `title` 1–256 characters (the issue title limit, since it is reused in step 3), `start` and `end` RFC 3339 with an offset, `end` after `start`. Bad input returns `400 invalid_request` and **no provider is called**.
2. Calendar adapter → Team 5 → one Google Calendar `events.insert` on `primary` → event id.
3. `DropboxStorage.upload` → one Dropbox `files_upload` with `WriteMode.add` (never overwrites) → file info.
4. Issue adapter → Team 4 → one Trello `POST /1/cards` on the configured list → card id.
5. `201` with all three. No log line on success; the response carries `X-Request-ID`.

### Request trace: expected failure (illustrative)

Step 4 fails because Trello rejects the token.

1. Team 4 raises `ServiceError(ACCESS_DENIED)`; `_MappedIssueProvider` turns it into `PermissionDeniedError("Issue tracker create_issue failed")`.
2. The operation undoes step 3 (`storage.delete`) and step 2 (`calendar.delete`).
3. `app/main.py` returns `403 permission_denied` and writes one `request_failed` line with the operation, code, status and request id. No title, path or token is logged.

---

## 3. API and data model

**Authoritative contracts:** the three contract packages pinned in `requirements.txt` (links in the header). The HTTP shape of our storage routes is the one the shared storage conformance suite tests ([TESTING.md](TESTING.md)).

| Topic | Choice |
| --- | --- |
| Identifiers | Event and card ids are opaque strings from the partner; we return them and never parse them. A document is named by its path; its Dropbox `id` is returned too |
| Scope | Team 5 always uses the test account's `primary` calendar. Team 4 always uses the list in `TRELLO_LIST_ID`. A request cannot choose another |
| Calendar times | RFC 3339 with an explicit offset (`calendar_contract.timestamps`), passed through unchanged |
| Issue fields | `Issue` has only `id` and `title`; titles up to 256 characters (`MAX_TITLE_LENGTH`); list returns at most 100 (`MAX_LIST_LIMIT`) |
| Errors | Partner codes map onto our existing errors (section 5), so callers see one error body |

**Representative request and response (illustrative expected response, not yet observed):**

```
POST /workflows/meeting
Content-Type: application/json

{"title": "Design review", "start": "2026-11-20T15:00:00-05:00", "end": "2026-11-20T15:30:00-05:00"}

201 Created
{
  "event": {"id": "<google event id>", "title": "Design review", "start": "2026-11-20T15:00:00-05:00", "end": "2026-11-20T15:30:00-05:00"},
  "document": {"id": "id:<dropbox id>", "name": "<google event id>.md", "path": "/meetings/<google event id>.md", "size": 120, "modified_at": "2026-11-18T14:00:00Z", "etag": "<rev>", "type": null},
  "issue": {"id": "<trello card id>", "title": "Follow up: Design review"}
}
```

After implementation this is replaced by a sanitized observed response and the command that produced it.

**Information loss and limits**

- Mapping onto our storage error types loses the partner's own code: the issue tracker's `precondition_failed` (412) and `request_in_progress` (409) both become our `409 conflict`, and `idempotency_key_reused` (422) becomes `400`.
- Partner `not_found` becomes our `not_found`. The message names the step (for example "Calendar get failed"), which tells the caller which provider it was.
- The calendar's `retryable` flag and the issue tracker's `provider_involved` and `may_have_applied` information are not passed to the caller.
- Team 4 also offers `create_tagged_issue(title, creation_token)` for safe retries; our adapter does not use it yet.

**HW2 operations:** every storage route stays as it is. Other teams consume our storage through the standalone package `packages/team1_dropbox` (#49), not through our HTTP API.

---

## 4. Alternatives and tradeoffs

### Decision 1: map partner errors onto our existing error types

| | Chosen: reuse our errors (`InvalidRequestError`, `FileNotFoundError`, …) | Alternative: one error type per vertical |
| --- | --- | --- |
| Caller | One error body and one code table for every route | Three code sets |
| Our code | No new handlers in `app/main.py`; each adapter has one `_call` translation function | New exception classes, handlers and docs |
| Lost detail | Partner-specific codes (412 vs 409, 422 vs 400) | Kept |

**Why:** the caller of the composed operation needs to know whether to fix the input, re-authenticate, or check what happened, not which provider's table applies; the step name in the message says which provider failed. Translation is centralized in one function per adapter rather than in each route, so a new partner code is handled in one place.
**Revisit if** a caller needs to branch on a partner-specific outcome, such as an issue tracker precondition failure.

### Decision 2: import partner packages in-process, not call their HTTP services

Chosen per the TA. **Cost:** partner dependency pins become ours, which forced the Python 3.14 upgrade (#46); a partner bug runs inside our process. **Benefit:** no network hop to a second deployment; the in-memory fakes make the operation testable offline; swapping implementations is one environment variable.

### Decision 3: on a failed step, undo earlier steps (Proposed)

| | Proposed: undo earlier steps | Alternative: leave them, report a partial result |
| --- | --- | --- |
| Caller | Either everything exists or nothing does, except when an undo itself fails | Must clean up event and document by hand |
| Our code | A delete per completed step, in reverse order | Simpler |
| Risk | An undo can fail too; then the response must list what is left | Leftovers on every failure |

**Revisit if** a step's result is unknown (section 5): deleting something whose creation is unknown is not reliable, so that case is reported instead of undone.

---

## 5. Failure behavior and operations

### Partner errors to our errors

| Calendar `ErrorCode` | Issue Tracker `ErrorCode` | Our error | HTTP | Code |
| --- | --- | --- | --- | --- |
| `INVALID_INPUT` | `INVALID_INPUT`, `IDEMPOTENCY_KEY_REUSED` | `InvalidRequestError` | 400 | `invalid_request` |
| `NOT_FOUND` | `NOT_FOUND` | `FileNotFoundError` | 404 | `not_found` |
| `ACCESS_DENIED` | `ACCESS_DENIED` | `PermissionDeniedError` | 403 | `permission_denied` |
| `PROVIDER_UNAVAILABLE` | — | `ProviderUnavailableError` | 503 | `provider_unavailable` |
| — | `SERVICE_NOT_CONFIGURED` | `StorageNotConfiguredError` | 503 | `provider_not_configured` |
| — | `PRECONDITION_FAILED`, `REQUEST_IN_PROGRESS` | `FileConflictError` | 409 | `conflict` |
| `PROVIDER_ERROR`, any other exception | `PROVIDER_ERROR`, `INTERNAL_ERROR`, any other exception | `ProviderError` | 502 | `provider_error` |

Missing configuration (`TEAM5_TOKEN_FILE`, any `TRELLO_*`) or an unknown `CALENDAR_IMPL`/`TRACKER_IMPL` raises `StorageNotConfiguredError` (503) before any provider call.

### Uncertain writes and retries

- **Calendar:** Team 5 calls Google with `num_retries=0` and reports whether the write had started.
- **Issue tracker:** Team 4 sets `may_have_applied` on a create that failed with a 5xx or after the request was sent; its contract lists `provider_error` and `internal_error` as outcome unknown.
- **Ours:** the service never retries a write inside a request, because a blind retry can create a second event, document or card. An unknown outcome is reported as `502 provider_error`, and the caller checks before trying again.
- **Proposed** for the composed operation: the response lists each step as `done`, `failed`, `undone` or `unknown`, so the caller knows what to check.

### Configuration, credentials and logging

- All credentials are environment variables (`.env` locally, never committed): `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`; `TEAM5_TOKEN_FILE` (path to the test account's Google OAuth token file; Team 5 never starts a browser login during a request); `TRELLO_API_KEY`, `TRELLO_TOKEN`, `TRELLO_LIST_ID`.
- On the OCI VM they go in `~/sandbox/.env` next to the Dropbox ones ([docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)). ⚠️ TBD: where the Team 5 token file is stored on the VM, and whether CI gets calendar and Trello secrets.
- Logging stays as in HW2: one `request_failed` line per failed request with the operation, code, status and request id. Event titles, card titles, file paths, tokens and partner messages are never logged.

### Cost of the composed operation (proposed)

| Step | Provider calls | Source |
| --- | --- | --- |
| Calendar create | 1 Google Calendar `events.insert`, plus a token refresh when the access token has expired | `team5_calendar/google_create_events.py` |
| Storage upload | 1 Dropbox `files_upload` | [docs/COST.md](docs/COST.md), unchanged |
| Issue create | 1 Trello `POST /1/cards`, 10-second timeout | `team_4_issue_tracker_trello/provider.py` |
| Undo after a failure | 1 delete per completed step | same files |

Local work is validation and building the notes text. Latency is not used to infer anything about the providers.

### Cleanup

Live runs create real events, documents and cards. The smoke scripts (`scripts/smoke_team5_calendar.py`, `scripts/smoke_team4_issue_tracker.py`) delete what they create. **Proposed:** the composed operation's live test uses titles starting with `HW3 test`, writes documents under `/integration-tests/`, and deletes all three in a `finally` block.

### Deployment

Docker image on an OCI VM, deployed by pushing a `deploy-oci-*` tag ([docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)). Today `deploy-oci.yml` and `ci.yml` only reference `hw2-milestone3`, so **neither CI nor deploy runs for `hw3-milestone1`**. Both need the branch name changed before the operation can be deployed from `hw3-milestone1`.

---

## 6. Migration and coordination plan

**Contract revisions adopted:** storage `0.2.0` in the service, calendar `v0.1.0`, issue tracker `v1.1.0`. Storage `0.3.1` only adds `open_download` and `create_stream`, both with default implementations that reuse `download` and `create`; the standalone package already targets it. **Proposed:** keep the service on `0.2.0` for this milestone and move to `0.3.1` when we need streaming.

### What changes

| Area | Change | Effect on existing callers |
| --- | --- | --- |
| Python | 3.12 → 3.14 (#46) | Developers, CI and the Docker image need 3.14 |
| Dependencies | Partner contract and implementation packages pinned to tags | None |
| Configuration | New `CALENDAR_IMPL`, `TEAM5_TOKEN_FILE`, `TRACKER_IMPL`, `TRELLO_*` | Defaults are the fakes, so nothing changes until set |
| Routes | `POST /workflows/meeting` (proposed) | Additive |
| Storage routes | None | None |

### Work breakdown

| Work | Owner | Depends on | Verification |
| --- | --- | --- | --- |
| Calendar integration | Dayana | Python 3.14 | `tests/test_calendar_integration.py`, `scripts/smoke_team5_calendar.py` (#47, merged) |
| Issue tracker integration | Dayana | Calendar integration | `tests/test_issue_tracker_integration.py`, `scripts/smoke_team4_issue_tracker.py` (#48) |
| Bring #48 into `hw3-milestone1` | Unassigned | — | One PR from `hw3-integrate-calendar-api`; 565 tests pass |
| Standalone Dropbox package | Yashwanth | — | `packages/team1_dropbox/tests` (#49, merged into `hw2-milestone3`); still needs a tag and to reach `hw3-milestone1` (issue #50) |
| Composed operation (route, undo, tests) | Unassigned | #48 on `hw3-milestone1` | Fake-backed route tests, one live run |
| CI and deploy for `hw3-milestone1` | Unassigned (Yashwanth built the deploy workflow) | — | Green CI run, deployed `/health` |
| DESIGN.md | Shini | — | Internal and external review |

**Early end-to-end step:** run the composed operation once against all three real providers with the test account as soon as the route exists, before polishing tests. That catches credential, list-id and time-format problems early.

### If a contract changes

Whoever finds the problem opens an issue on the owning team's repository with a reproduction and does not patch the contract alone. We move a pin only when the owner publishes a new tag. Consumers of **our** storage package (Team 2, issue #50) are told in the shared Slack channel before we publish an incompatible storage tag.

### Issue tracker: one behavior, two implementations

The service only sees `IssueProvider` from `issue_tracker_contract`. `TRACKER_IMPL=fake` gives `InMemoryIssueProvider` (tests and local runs); `TRACKER_IMPL=team4` gives Team 4's `TrelloIssueProvider`. Both go through the same `_MappedIssueProvider`, so the composed operation behaves the same with either. What differs is only below the contract: the fake keeps cards in a dict and never fails unless a failure is injected; Trello needs three settings, makes one HTTP request per call and can report an unknown outcome. Switching is a startup choice; there is no runtime switching. Calendar works the same way with `CALENDAR_IMPL=fake|team5`.

---

## 7. Testing

| Guarantee | Check | Level |
| --- | --- | --- |
| Config picks the right implementation and rejects unknown or incomplete settings | Factory tests in `test_calendar_integration.py` and `test_issue_tracker_integration.py` | Fast, no network |
| Every partner error code maps to the documented error | `test_contract_errors_map_to_application_errors` (both files) | Fast |
| An unexpected partner exception becomes `provider_error` and names the step | `test_unexpected_error_maps_to_provider_error_with_step_name` (both files) | Fast |
| Fakes behave like the contract and can fail on demand | `test_fake_can_inject_failure_for_chosen_method`, `test_fake_supports_update_list_and_delete` | Fast |
| The real partner packages work with our credentials | `scripts/smoke_team5_calendar.py`, `scripts/smoke_team4_issue_tracker.py` (skip unless configured; delete what they create) | Live, run by hand |
| Storage still matches the shared contract | Shared storage conformance suite in CI ([TESTING.md](TESTING.md)) | Live, real Dropbox |
| Composed operation: success, each step failing, undo, unknown outcome | **Proposed:** `tests/test_workflow_meeting.py` with both fakes and fake storage, injecting a failure per step | Fast |
| Composed operation against real providers | **Proposed:** one live test per the cleanup rule in section 5 | Live |

**Conformance suites**
- **Storage:** the shared suite runs in our CI against real Dropbox; 51/55 pass, and the 4 failures are rules still marked proposed ([TESTING.md](TESTING.md)).
- **Calendar:** `calendar_contract.conformance.CalendarServiceConformance` ships with the contract; a test subclasses it and provides two fixtures, `service` and `failing_service` (a factory for an implementation whose provider fails every call). **Proposed:** run it against `InMemoryCalendarService` so our fake is held to the same rules as Team 5.
- **Issue tracker:** Team 4 keeps its suite in `contract/tests/conformance` and runs it against its providers.
- A mismatch would show up as a failing conformance test, for example our fake accepting a timestamp without an offset that the contract rejects.

**Contract mismatches found so far:** none. The partner packages have not yet been run live from our service, so this is not evidence of compatibility; the smoke scripts and the early end-to-end step check it.

**Known gaps:** no test covers more than one vertical in one request yet, and the live smoke scripts are not in CI.

---

## 8. Open questions and review

| # | Question | Consequence | Owner | Next step |
| --- | --- | --- | --- | --- |
| 1 | Is `POST /workflows/meeting` the fixed-step operation? | Sections 2–7 assume it | ⚠️ TBD | Team confirms or replaces it |
| 2 | Undo earlier steps on failure (Decision 3)? | What the caller must clean up | Same as 1 | Decide with question 1 |
| 3 | Stay on storage `0.2.0` or move to `0.3.1`? | Only adds streaming methods with defaults | Same as 1 | Proposed: stay for M1 |
| 4 | CI and deploy for `hw3-milestone1` | Required for a deployed operation | Unassigned | Change the branch in `ci.yml` and `deploy-oci.yml` |
| 5 | Partner credentials on the VM and in CI | The deployment cannot call Teams 4 and 5 without them | Unassigned | See section 5 |

### Review log

| Reviewer | Comment | Response | Outcome |
| --- | --- | --- | --- |
| — | No comments yet | — | — |

---

## 9. Actions

| Task | Owner | Output | Depends on | Target |
| --- | --- | --- | --- | --- |
| Confirm the composed operation | Team | Question 1 closed | — | Nov 18 |
| Merge the issue tracker into `hw3-milestone1` | Unassigned | PR | — | Nov 18 |
| Build and test the composed operation | Unassigned | PR, observed response in section 3 | Two rows above | Nov 18 |
| CI and deploy for `hw3-milestone1` | Unassigned | Green run, deployed `/health` | — | Nov 18 |
| Internal review of this document | Internal reviewer | PR comments | Draft complete | Nov 18 |
| External review of sections 3, 6 and 7 | External reviewer | PR comments, answered in the review log | Draft complete | Before Milestone 2 |

## Change record

| Date | What changed | Why |
| --- | --- | --- |
| Nov 18, 2026 | HW3 design written; HW2 design moved to `docs/DESIGN-HW2.md` | HW3 Milestone 1 |
