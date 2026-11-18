# HW3 Milestone 1: verification evidence

The composed operation is `POST /workflows/meeting`: it creates a calendar event (calendar vertical), saves a notes document for it (storage vertical, ours), and opens a follow-up issue (issue tracker vertical). Design: [DESIGN.md](../DESIGN.md).

Everything below was run on Nov 18, 2026. Sections 1–4 ran on branch `shini/hw3-workflow` (on top of `hw3-milestone1` at `8af9112`); sections 1b and 1c on `hw3-milestone1` at `b9a6547` after it merged. Storage was **real Dropbox** in every run; section 1c uses the real calendar and issue tracker too. Ids are from test data that was deleted afterwards; no credentials appear here.

## How to run it

```bash
# Python 3.14, from the repo root
pip install -r requirements.txt
# .env: DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN
# Choose the implementations (default: fake for both):
#   CALENDAR_IMPL=fake | team5   (team5 needs TEAM5_TOKEN_FILE)
#   TRACKER_IMPL=fake  | team4   (team4 needs TRELLO_API_KEY, TRELLO_TOKEN, TRELLO_LIST_ID)
uvicorn app.main:app --port 8000

curl -i -X POST http://127.0.0.1:8000/workflows/meeting \
  -H "Content-Type: application/json" \
  -d '{"title": "Design review", "start": "2026-11-20T15:00:00-05:00", "end": "2026-11-20T15:30:00-05:00"}'
```

`start` and `end` must be RFC 3339 with an offset; the title can be at most 245 characters so the issue title `Follow up: <title>` fits Team 4's 256-character limit.

## 1. Workflow across all three verticals

`CALENDAR_IMPL=fake`, `TRACKER_IMPL=fake`, real Dropbox:

```
HTTP/1.1 201 Created
{"event":{"id":"792f07d875d540208db1098ef6990515","title":"HW3 test meeting","start":"2026-11-20T15:00:00-05:00","end":"2026-11-20T15:30:00-05:00"},
 "document":{"id":"id:QqRAUO3-OU4AAAAAAAAGKA","name":"792f07d875d540208db1098ef6990515.md","path":"/meetings/792f07d875d540208db1098ef6990515.md","size":150,"modified_at":"2026-11-18T20:58:16Z","etag":"0166093451cf55e0000000391630f83","type":null},
 "issue":{"id":"b9aa4603d2a641eeadb1edb59a5ea8f5","title":"Follow up: HW3 test meeting"}}
```

The document really is in Dropbox (`GET /files/download?path=/meetings/792f07d8….md`):

```
# HW3 test meeting

- Start: 2026-11-20T15:00:00-05:00
- End: 2026-11-20T15:30:00-05:00
- Calendar event: 792f07d875d540208db1098ef6990515
```

Bad input is refused before any provider is called (time without an offset):

```
HTTP/1.1 400 Bad Request
{"error":{"code":"invalid_request","message":"title, start and end must be a non-empty title and RFC 3339 times with an offset, with end after start"}}
```

### 1b. With Team 4's real Trello implementation

Same request on `hw3-milestone1` at `b9a6547`, with `TRACKER_IMPL=team4` and valid Trello settings for our test board (`CALENDAR_IMPL=fake`, real Dropbox):

```
HTTP/1.1 201 Created
{"event":{"id":"5ea6353ac0564767a27972bd96128f5a","title":"HW3 live test","start":"2026-11-20T15:00:00-05:00","end":"2026-11-20T15:30:00-05:00"},
 "document":{"id":"id:QqRAUO3-OU4AAAAAAAAINA","name":"5ea6353ac0564767a27972bd96128f5a.md","path":"/meetings/5ea6353ac0564767a27972bd96128f5a.md","size":147,"modified_at":"2026-11-18T22:08:01Z","etag":"01660943e8f91070000000391630f83","type":null},
 "issue":{"id":"6afe21c1da6f219b72798d76","title":"Follow up: HW3 live test"}}
```

The issue id is a real Trello card id. Reading it back through Team 4's provider (`get_issue`) returned the title `Follow up: HW3 live test`. The card and the Dropbox document were then deleted.

### 1c. All three real implementations

Same request on `hw3-milestone1` at `b9a6547` with **every vertical real**: `CALENDAR_IMPL=team5` (Team 5's package, Google Calendar, our own test Google account authorized with `python -m team5_calendar.authorize`), `TRACKER_IMPL=team4` (Team 4's package, our Trello board) and our Dropbox:

```
HTTP/1.1 201 Created
{"event":{"id":"35s47dnsl44qchkmds3ob6c44c","title":"HW3 full live test","start":"2026-11-20T15:00:00-05:00","end":"2026-11-20T15:30:00-05:00"},
 "document":{"id":"id:QqRAUO3-OU4AAAAAAAAINg","name":"35s47dnsl44qchkmds3ob6c44c.md","path":"/meetings/35s47dnsl44qchkmds3ob6c44c.md","size":146,"modified_at":"2026-11-18T22:26:34Z","etag":"016609480e970320000000391630f83","type":null},
 "issue":{"id":"6afe261a4d1389917f8cac45","title":"Follow up: HW3 full live test"}}
```

Each item was then read back through its own provider:

```
Google Calendar event: HW3 full live test 2026-11-20T15:00:00-05:00   (Team 5 calendar.get)
Trello card: Follow up: HW3 full live test                            (Team 4 get_issue)
Dropbox doc first line: # HW3 full live test                          (Dropbox files_download)
```

All three were deleted afterwards. The credentials (Google token file, Trello key and token) live outside the repository and are not shown here.

## 2. Switching implementations through configuration

Same code, same request; only environment variables change. With a real implementation selected but not configured, the request fails with `503` **before any step runs** (nothing in Dropbox afterwards):

```
TRACKER_IMPL=team4, Trello settings empty
HTTP/1.1 503 Service Unavailable
{"error":{"code":"provider_not_configured","message":"Required when TRACKER_IMPL=team4: TRELLO_API_KEY, TRELLO_TOKEN, TRELLO_LIST_ID"}}

CALENDAR_IMPL=team5, TEAM5_TOKEN_FILE empty
HTTP/1.1 503 Service Unavailable
{"error":{"code":"provider_not_configured","message":"TEAM5_TOKEN_FILE is required when CALENDAR_IMPL=team5"}}
```

Run 3 below also uses `TRACKER_IMPL=team4`: Team 4's real Trello package, selected only by configuration.

## 3. Handling a dependency failure

`CALENDAR_IMPL=fake`, `TRACKER_IMPL=team4` with an **invalid** Trello key and token, real Dropbox. The calendar event and the Dropbox document were created, then Team 4's package called Trello, which refused:

```
HTTP/1.1 403 Forbidden
{"error":{"code":"permission_denied","message":"Issue tracker create_issue failed; earlier steps were undone"}}
```

Afterwards `GET /files?path=/meetings` returned `[]`: the document that had been written to Dropbox was deleted again. The event was deleted too (the fake calendar lives in memory, so that part is checked by `test_issue_tracker_refusal_undoes_event_and_document`). The server log has one line, with no title or path:

```
request_failed operation=create_meeting error=permission_denied status=403 provider=yes request_id=96dca6fc24c64285a737bac8c884ddda
```

## 4. Automated tests

`tests/test_workflow_meeting.py` (17 tests, no network) covers: success across all three, the 245-character title edge, five kinds of bad input creating nothing, each step failing (calendar unavailable, storage refused, issue tracker refused), an unknown issue-tracker outcome reported as "may have completed", an undo that itself fails being named in the error, implementation selection by configuration, and no title in the failure log.

```
pytest      580 passed
ruff check  All checks passed
mypy app    no issues found in 41 source files
```

## Still to do

- Deploy this branch (merge into `hw3-milestone1`, push a `deploy-oci-*` tag; see [DEPLOYMENT.md](DEPLOYMENT.md)) and set `CALENDAR_IMPL`, `TEAM5_TOKEN_FILE`, `TRACKER_IMPL` and `TRELLO_*` in the VM's `.env`.
