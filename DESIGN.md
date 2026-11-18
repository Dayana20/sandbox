# DESIGN: Team 1 composes Storage, Calendar and Issue Tracker (HW3 Milestone 1)

> Items marked **⚠️ TO FILL** are not decided or not built yet. Whoever owns that part replaces the marker with the real answer.

| | |
| --- | --- |
| **Title** | Team 1 composes Storage, Calendar and Issue Tracker behind one API operation |
| **Authors** | ⚠️ TO FILL |
| **Team / vertical** | Team 1, Document Storage (Dropbox) |
| **Internal reviewer** | ⚠️ TO FILL (a teammate who did not write the section) |
| **External reviewer** (contract-facing parts: sections 3, 6 and 7) | ⚠️ TO FILL (someone from another team) |
| **Status** | Draft |
| **Last updated** | Nov 18, 2026 |
| **Shared contracts** | Storage: [ospsd26-cloud-storage](https://github.com/Dayana20/ospsd26-cloud-storage) `0.2.0` (service) and `0.3.1` (latest tag). Calendar: [OSPSD-Calendar](https://github.com/Airbus-A330/OSPSD-Calendar) `calendar-contract` `v0.1.0`. Issue Tracker: [OSPSD-Team-4](https://github.com/Tyler-Arciniaga/OSPSD-Team-4) `issue-tracker-contract-v1.1.0` |
| **Implementations used** | Storage: ours (Dropbox). Calendar: Team 5 `team5-calendar-v0.1.0`. Issue Tracker: Team 4 Trello `team-4-issue-tracker-trello-v1.0.0` |
| **Decision memo** | HW2 storage memo: [docs/DESIGN-HW2.md](docs/DESIGN-HW2.md) links it. ⚠️ TO FILL: link to any HW3 cross-team agreement |
| **Implementation work** | Python 3.14 (#46), calendar integration (#47), issue tracker integration (#48), standalone Dropbox package (#49). ⚠️ TO FILL: the PR for the composed operation |

The HW2 design (how our service adopted the shared storage contract) is kept in [docs/DESIGN-HW2.md](docs/DESIGN-HW2.md).

---

## 1. Context, goals, non-goals

### Context

HW2 made each vertical a shared contract: storage (`cloud_storage_api`), calendar (`calendar_contract`) and issue tracking (`issue_tracker_contract`). In HW3 a consumer wants one request that does work in all three places, for example "create a meeting, save its notes, and open a follow-up issue", without writing code for each provider.

Per the TA, a team consumes another vertical by importing that team's **implementation package in-process**, not by calling their deployed HTTP API. So Team 1's service installs Team 5's calendar package and Team 4's Trello package and calls them through their contracts.

What makes this hard today, concretely:

| Difference | Storage (ours) | Calendar (Team 5) | Issue Tracker (Team 4) | What a caller could get wrong |
| --- | --- | --- | --- | --- |
| Error type | Our `StorageError` subclasses, HTTP body `{"error": {"code", "message"}}` | `CalendarError(code, message, retryable)` | `ServiceError(code, message, provider_involved)` | Three exception types and three code sets for one request |
| "Bad input" | `400 invalid_request` | `ErrorCode.INVALID_INPUT` | `invalid_input`, which the contract maps to **422** | The same mistake would surface as 400 from one step and 422 from another |
| Uncertain write | `502 provider_error` (check before retrying) | `retryable` flag on the error | `provider_error` and `internal_error` are in `OUTCOME_UNKNOWN_CODES` | A caller that blindly retries can create a second event or issue |
| Identifiers | Path (`/docs/a.pdf`) plus an opaque Dropbox `id` | Opaque event `id` | Opaque issue `id` | Three id kinds to keep together to undo or look up a run |
| Time format | `modified_at` UTC ending in `Z` | RFC 3339 with an **explicit offset**; naive times are rejected | none | A timestamp valid for storage can be rejected by the calendar |

### Goals (observable)

1. One deployed API operation runs fixed steps across storage, calendar and issue tracker for one test account, and returns the ids it created. ⚠️ TO FILL once the route exists: its URL and a recorded run.
2. Every failure, whichever step it comes from, uses our one error body `{"error": {"code", "message"}}` and names the step that failed. A write whose result is unknown is reported as unknown, never as "nothing happened".
3. Each partner implementation can be replaced by configuration only (`CALENDAR_IMPL`, `TRACKER_IMPL`), with no code change. The same operation runs unchanged against the in-memory fakes and the real providers.
4. Existing storage routes behave exactly as in HW2 and keep passing the shared storage conformance suite.

### Non-goals

- **A product, an agent, a user interface or user accounts.** Milestone 2 adds those. This milestone uses one fixed test account per provider.
- **Calling other teams' deployed services over HTTP.** We import their packages, as the TA clarified.
- **Distributed transactions.** The three providers cannot commit together. We undo what we can and report what we cannot (section 5).
- **Using every partner feature.** Only the operations the composed workflow needs are used.

---

## 2. Architecture and request flow

### Components

| Component | File | Responsibility | Status |
| --- | --- | --- | --- |
| Shared contract packages | `cloud_storage_api`, `calendar_contract`, `issue_tracker_contract` (pinned in `requirements.txt`) | Types, interfaces and error codes we code against | Installed |
| Partner implementations | `team5_calendar`, `team_4_issue_tracker_trello` | Talk to the real calendar and Trello | Installed |
| Calendar adapter | `app/integrations/calendar.py` | Picks the implementation from `CALENDAR_IMPL`, maps `CalendarError` codes to our errors, includes `InMemoryCalendarService` | Done (#47) |
| Issue tracker adapter | `app/integrations/issue_tracker.py` | Picks the implementation from `TRACKER_IMPL`, maps `ServiceError` codes to our errors, includes `InMemoryIssueProvider` | Done in #48. ⚠️ TO FILL: #48 was merged into `hw3-integrate-calendar-api` after #47 had merged, so it is **not yet on `hw3-milestone1`** |
| Storage | `app/providers/dropbox/` (`DropboxStorage`), `app/dependencies.py` | Unchanged from HW2 | Done |
| Composed operation | ⚠️ TO FILL: route file and service function | Runs the fixed steps, undoes earlier steps on failure, returns all ids | **Not built** |
| Error handling | `app/main.py`, `app/errors.py` | Turns our domain errors into the HTTP error body | Done |
| Startup configuration | `app/core/config.py`, `.env` | `CALENDAR_IMPL`, `TEAM5_TOKEN_FILE`, `TRACKER_IMPL`, `TRELLO_*`, `DROPBOX_*` | Done |

**Dependency direction.** Routes depend only on our interfaces (`DocumentStorage`, the calendar and issue `get_*` factories). Only the adapters import partner packages. Partner exceptions are translated inside the adapters and never reach a route.

**Who creates and closes clients, and who owns state.**
- Dropbox: one client, created on first use and cached (`get_dropbox_client()`), as in HW2.
- Calendar: `get_calendar_service()` builds a service on each call. With `CALENDAR_IMPL=team5`, Team 5's service is bound to the OAuth token file in `TEAM5_TOKEN_FILE` and authorizes on its first call.
- Issue tracker: `get_issue_provider()` builds a provider on each call. With `TRACKER_IMPL=team4`, it reads `TRELLO_API_KEY`, `TRELLO_TOKEN` and `TRELLO_LIST_ID`.
- ⚠️ TO FILL: whether the composed route builds the calendar and tracker once at startup or per request.
- State: Team 1 keeps no application state for this operation. Events live in the test calendar, issues on the Trello list, documents in our Dropbox app folder.

### The composed operation

⚠️ TO FILL: the team has not fixed the operation yet. **Proposed for discussion, replace or confirm:**

> `POST /workflows/meeting` with `{"title", "start", "end"}`:
> 1. **Calendar:** create the event.
> 2. **Storage:** save a notes document at `/meetings/<event-id>.md`.
> 3. **Issue tracker:** create the issue `Follow up: <title>`, mentioning the document path.
>
> Returns `201` with the event id, the document's file info and the issue id.

Guarantees it needs: each step runs at most once per request; a later step only runs if the earlier ones succeeded; the response either lists everything created or says which step failed and what may be left behind.

Deliberate limits: one test account per provider; no retries inside the request; no update or delete operation across all three.

### Request trace: success

⚠️ TO FILL after implementation. Expected shape, for the proposed operation:

1. The route validates the body: title present, `start`/`end` RFC 3339 with an offset, `end` after `start`. Bad input returns `400 invalid_request` and **no provider is called**.
2. Calendar adapter: `create(CreateEvent(...))` → Team 5 → event id.
3. Storage: `upload("/meetings/<event-id>.md", notes)` → Dropbox `files_upload` (never overwrites) → file info.
4. Issue adapter: `create_issue("Follow up: …")` → Team 4 → Trello → issue id.
5. The route returns `201` with all three. No log line on success; every response carries `X-Request-ID`.

### Request trace: expected failure

⚠️ TO FILL after implementation. Expected shape: step 4 fails because Trello rejects the token.

1. Team 4 raises `ServiceError(ACCESS_DENIED)`; the issue adapter maps it to `PermissionDeniedError`.
2. The operation undoes steps 3 and 2: delete the document, delete the event.
3. `app/main.py` returns `403 permission_denied` and writes one `request_failed` line with the operation and request id, no titles or paths.

---

## 3. API and data model

**Authoritative contracts:** the three packages pinned in `requirements.txt` (links in the header). The HTTP shape of our storage routes is the one tested by the shared storage conformance suite ([TESTING.md](TESTING.md)).

**Important choices**

| Topic | Choice |
| --- | --- |
| Identifiers | Event and issue ids are opaque strings from the partner; we store and return them, never parse them. A storage file is named by its path; its Dropbox `id` is also returned |
| Scope | One calendar and one Trello list per deployment, set by configuration. A request cannot choose another |
| Calendar times | `start` and `end` must be RFC 3339 with an explicit offset (`calendar_contract.timestamps`); we pass them through unchanged |
| Issue fields | `Issue` has only `id` and `title`. Titles are limited to 256 characters (`MAX_TITLE_LENGTH`); list returns at most 100 (`MAX_LIST_LIMIT`) |
| Errors | Partner codes map to our existing errors (table in section 5), so callers see one error body |

**Representative request and response:** ⚠️ TO FILL. At proposal time this would be an *illustrative expected response*; after implementation, a sanitized observed response and how it was produced.

**Information loss and limits**

- Mapping partner errors onto our storage error types loses the partner's own code. For example, the issue tracker's `precondition_failed` (412) and `request_in_progress` (409) both become our `409 conflict`, and its `idempotency_key_reused` becomes `400`.
- Partner `not_found` becomes our `not_found`, whose message currently says "File not found" style text; the step name in the message tells the caller which provider it was.
- The calendar's `retryable` flag and the issue tracker's `provider_involved` flag are not exposed to the caller.

**HW2 operations:** every storage route stays as it is and is not part of the composed operation's contract. The standalone package in `packages/team1_dropbox` (#49) is how other teams consume our storage.

---

## 4. Alternatives and tradeoffs

### Decision 1: map partner errors onto our existing error types

| | Chosen: reuse our errors (`InvalidRequestError`, `FileNotFoundError`, …) | Alternative: one error type per vertical |
| --- | --- | --- |
| Caller | One error body and one code table for every route | Must handle three code sets |
| Our code | No new handlers in `app/main.py`; adapters are short | New exception classes, handlers and docs |
| Lost detail | Partner-specific codes (e.g. 412 vs 409) | Kept |

**Why:** the caller of the composed operation needs to know whether to fix the input, re-authenticate, or check what happened, not which provider's code table applies. The step name in the message says which provider failed.
**Revisit if** a caller needs to branch on a partner-specific outcome, such as an issue tracker precondition failure.

### Decision 2: import partner packages in-process, not call their HTTP services

Chosen per the TA's clarification. **Cost:** partner bugs and dependency pins become ours; the Python 3.14 upgrade (#46) was needed for their packages. **Benefit:** no network hop or second deployment to depend on; the fakes make the operation testable offline.

### Decision 3: ⚠️ TO FILL (how the composed operation handles a failed step)

Expected options: undo earlier steps (delete the event and document) versus leave them and report a partial result. The choice decides what a caller must clean up.

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

- The issue tracker contract marks `provider_error` and `internal_error` as "outcome unknown": the issue may have been created. We report these as `502` and do not retry.
- The service never retries a write inside a request. A blind retry could create a second event, document or issue.
- ⚠️ TO FILL: how the composed operation reports an unknown outcome in one step (for example, list each step as `done`, `failed`, `undone` or `unknown`), and what the caller should check before retrying.

### Configuration, credentials and logging

- All credentials are environment variables (`.env` locally, never committed): `DROPBOX_*`, `TEAM5_TOKEN_FILE` (path to Team 5's OAuth token file), `TRELLO_API_KEY`, `TRELLO_TOKEN`, `TRELLO_LIST_ID`.
- ⚠️ TO FILL: where the Team 5 token file and the Trello credentials live on the OCI VM and in CI.
- Logging stays as in HW2: one `request_failed` line per failed request with the operation, code, status and request id. Event titles, issue titles, file paths, tokens and partner messages are never logged.

### Cost of the composed operation

⚠️ TO FILL after implementation: provider calls per step. Known so far: storage upload is 1 Dropbox call ([docs/COST.md](docs/COST.md) still applies). Calendar create and issue create are one contract call each; how many provider requests each makes is inside the partner package and not measured.

### Cleanup

Live runs create real events, documents and issues. Smoke scripts (`scripts/smoke_team5_calendar.py`, `scripts/smoke_team4_issue_tracker.py`) delete what they create. ⚠️ TO FILL: the cleanup rule for the composed operation's live test.

### Deployment

Docker image on an OCI VM, deployed by pushing a `deploy-oci-*` tag ([docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)). ⚠️ TO FILL: `deploy-oci.yml` and `ci.yml` only reference `hw2-milestone3`, so neither CI nor deploy runs for `hw3-milestone1` today. Owner and fix needed before the operation can be "deployed".

---

## 6. Migration and coordination plan

**Contract revisions adopted:** storage `0.2.0` in the service (⚠️ TO FILL: decide whether to move to `0.3.1`, which the standalone package already uses), calendar `v0.1.0`, issue tracker `v1.1.0`.

### What changes

| Area | Change | Effect on existing callers |
| --- | --- | --- |
| Python | 3.12 → 3.14 (#46) | Developers and CI need 3.14 |
| Dependencies | Partner contract and implementation packages pinned to tags | None |
| Configuration | New `CALENDAR_IMPL`, `TEAM5_TOKEN_FILE`, `TRACKER_IMPL`, `TRELLO_*` | Defaults are the fakes, so nothing changes until set |
| Routes | ⚠️ TO FILL: the composed operation's route | Additive |
| Storage routes | None | None |

### Work breakdown

| Work | Owner | Depends on | Verification |
| --- | --- | --- | --- |
| Calendar integration | Dayana | Python 3.14 | `tests/test_calendar_integration.py`, `scripts/smoke_team5_calendar.py` (#47) |
| Issue tracker integration | Dayana | Calendar integration | `tests/test_issue_tracker_integration.py`, `scripts/smoke_team4_issue_tracker.py` (#48) |
| Bring #48 into `hw3-milestone1` | ⚠️ TO FILL | — | 565 tests pass on `hw3-milestone1` |
| Standalone Dropbox package for other teams | Yashwanth | — | `packages/team1_dropbox/tests` (#49). ⚠️ TO FILL: tag it and bring it into `hw3-milestone1` (issue #50) |
| Composed operation (route, undo, tests) | ⚠️ TO FILL | Both integrations on `hw3-milestone1` | Fake-backed route tests, one live run |
| CI and deploy for `hw3-milestone1` | ⚠️ TO FILL | — | Green CI run, deployed health check |
| DESIGN.md | Shini | — | Internal and external review |

**Early end-to-end step:** run the composed operation once against all three real providers with the test account as soon as the route exists, before polishing tests, to catch credential and time-format problems early.

### If a contract changes

Whoever finds the problem opens an issue on the owning team's repository with a reproduction and does not patch the contract alone. We move our pin only when the owner publishes a new tag. Consumers of **our** storage package (Team 2 via issue #50, ⚠️ TO FILL: others) are told in the shared Slack channel before we publish a breaking storage tag.

### Issue tracker: one behavior, two implementations

The service only sees `IssueProvider` from `issue_tracker_contract`. `TRACKER_IMPL=fake` gives `InMemoryIssueProvider` (tests and local runs); `TRACKER_IMPL=team4` gives Team 4's Trello provider. Both go through the same error mapping (`_MappedIssueProvider`), so the composed operation behaves the same with either. Switching is a startup configuration choice; there is no runtime switching. Calendar works the same way with `CALENDAR_IMPL=fake|team5`.

---

## 7. Testing

| Guarantee | Check | Level |
| --- | --- | --- |
| Config picks the right implementation, and rejects unknown or incomplete settings | `test_calendar_integration.py` (factory tests), `test_issue_tracker_integration.py` (factory tests) | Fast, no network |
| Every partner error code maps to the documented error | `test_contract_errors_map_to_application_errors` in both files | Fast |
| An unexpected partner exception becomes `provider_error` and names the step | `test_unexpected_error_maps_to_provider_error_with_step_name` in both files | Fast |
| Fakes can inject a failure for one method | `test_fake_can_inject_failure_for_chosen_method`, `test_fake_supports_update_list_and_delete` | Fast |
| The real partner packages work with our credentials | `scripts/smoke_team5_calendar.py`, `scripts/smoke_team4_issue_tracker.py` (skip unless configured; delete what they create) | Live |
| Storage still matches the shared contract | Shared storage conformance suite in CI ([TESTING.md](TESTING.md)) | Live, real Dropbox |
| Composed operation: success, each step failing, undo, unknown outcome | ⚠️ TO FILL | Fast (with fakes) |
| Composed operation against real providers | ⚠️ TO FILL | Live |

**Conformance suites:** storage runs in our CI. ⚠️ TO FILL: whether the calendar and issue tracker verticals publish conformance suites, and whether we run them against Team 5's and Team 4's packages.

**Known gaps:** no test yet covers more than one vertical in one request, and the live smoke scripts are run by hand, not in CI.

---

## 8. Open questions and review

| # | Question | Consequence | Owner | Next step |
| --- | --- | --- | --- | --- |
| 1 | What is the fixed-step operation? | Sections 2–7 depend on it | ⚠️ TO FILL | Team decides; update this document |
| 2 | Undo earlier steps on failure, or report a partial result? | What the caller must clean up | ⚠️ TO FILL | Decide with question 1 |
| 3 | Move the service from storage `0.2.0` to `0.3.1`? | Matches the package other teams install | ⚠️ TO FILL | Diff the two tags |
| 4 | How do CI and deploy run for `hw3-milestone1`? | Milestone requires a deployed operation | ⚠️ TO FILL | Update `ci.yml` and `deploy-oci.yml` |
| 5 | Where do partner credentials live on the VM? | Deployment cannot call Team 4 and 5 without them | ⚠️ TO FILL | — |

**Contract mismatches reported to partner teams:** ⚠️ TO FILL (issue link and reproduction for each).

### Review log

| Reviewer | Comment | Response | Outcome |
| --- | --- | --- | --- |
| ⚠️ TO FILL | | | Changed / Explained / Accepted risk / Deferred (owner, date) |

---

## 9. Actions

| Task | Owner | Output | Depends on | Target |
| --- | --- | --- | --- | --- |
| Decide the composed operation | ⚠️ TO FILL | Sections 2–7 updated | — | Nov 18 |
| Merge the issue tracker into `hw3-milestone1` | ⚠️ TO FILL | PR | — | Nov 18 |
| Build and test the composed operation | ⚠️ TO FILL | PR | Two items above | Nov 18 |
| CI and deploy for `hw3-milestone1` | ⚠️ TO FILL | Green run, deployed health check | — | Nov 18 |
| Internal review of this document | ⚠️ TO FILL | PR comments | Draft complete | Nov 18 |
| External review of sections 3, 6 and 7 | ⚠️ TO FILL | PR comments, answered in the review log | Draft complete | ⚠️ TO FILL |

## Change record

| Date | What changed | Why |
| --- | --- | --- |
| Nov 18, 2026 | HW3 design started; HW2 design moved to `docs/DESIGN-HW2.md` | HW3 Milestone 1 |
