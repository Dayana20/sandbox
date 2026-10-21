# Extending a teammate's feature

Laya built two shared pieces in PR #9: `validate_path()`, the one path check every route uses, and `@logs_dropbox_errors`, the decorator that logs each Dropbox failure. After the sister-team review, Shini extended both in PR #18. The two changes spread very differently through the code, and the reason is how Laya's original design was shaped.

## Extension 1: reject control characters in paths

**What changed and why:** Turki (Team 4) pointed out that `validate_path()` accepted newlines and null bytes. They're never valid in a file name, and a newline would split a log line in two. The fix rejects any control character (ASCII 0-31 and 127) with `400 invalid_request`.

**Modules changed:**

| Module | Change |
| --- | --- |
| `app/validation.py` | One new check (3 lines) and its docstring |
| `tests/test_validation.py` | 4 new entries in the existing `BAD_PATHS` list |
| `README.md` | 1 new row in the Paths rules table |

**Why the change didn't spread:** all five routes (upload, metadata, download, move, delete) already call `validate_path()`, and none has a path check of its own. One new rule in one function covered all six path inputs, counting move's `path` and `new_path` separately, without opening a single route file. If each route had its own path check, the same fix would have meant six edits, and missing one would have left a gap.

**Tests that show it:** `test_validation.py` already ran every entry in `BAD_PATHS` both directly and through every route (`test_every_route_rejects_bad_path_before_storage`, with a storage that fails the test if it's ever called). Adding 4 bad paths therefore added 28 test cases: 4 direct plus 4 x 6 route inputs. Each one proves a path with a newline, null byte, tab or DEL gets `400` and never reaches Dropbox.

## Extension 2: stop logging file paths

**What changed and why:** Turki also pointed out that the Dropbox error log printed the full file path, and file names can contain private information. The `dropbox_error` log line now keeps the operation, error type, Dropbox error and Dropbox request id, but not the path.

**Modules changed:**

| Module | Change |
| --- | --- |
| `app/providers/dropbox/error_mapping.py` | The decorator no longer reads the path; the log format drops `path=` |
| `tests/test_dropbox_error_logging.py` | Two tests that asserted the path was logged now assert it isn't; one test about finding the path argument was removed as no longer relevant |
| `README.md` | The log example and field table lose `path` |
| `AGENTS.md` | The rule "never log tokens..." now includes file paths |

**Why the change spread further:** the code change was small. But the log line was documented as a format, in a README example and a table of fields, and two tests checked its exact contents. Behaviour, tests and docs all described the same thing, so all three had to change together. That's intended: if the tests hadn't failed, the docs would have kept promising a `path` field that no longer existed.

**What didn't need to change:** `app/providers/dropbox/storage.py`. All five `DropboxStorage` methods are wrapped by `@logs_dropbox_errors`, so changing the decorator changed the logging for every operation without editing any of them.

**Tests that show it:** `test_lookup_failure_is_logged_with_dropbox_detail` and `test_move_failure_is_logged_without_paths` assert that the file name is not in the log line, while the operation, error type and request id still are.

## What this shows

Both extensions were cheap because Laya's original design had a single choke point: one function for every path check, and one decorator for every Dropbox failure. A change in one place reached every route and every operation. The only extra cost was where behaviour was also written down as a contract, in tests and docs, and that cost is what keeps them accurate.
