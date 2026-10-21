# Cost of one operation: upload

We picked `POST /files` (upload) because it's the one operation whose work grows with the input: every byte of the file passes through our service on its way to Dropbox. By contrast, a move never touches the file's bytes (2 Dropbox calls whatever the size), and metadata and delete do a fixed amount of work.

Throughout, **n** is the file size in bytes. The limit is n ≤ 150 MB, which is the most Dropbox's `files_upload` accepts in one request.

## Where the work happens

| # | Step | Where | Time | Memory | Dropbox calls |
| --- | --- | --- | --- | --- | --- |
| 1 | Receive the multipart request. Files up to 1 MB stay in memory; larger ones are written to a temporary file on disk | Local (FastAPI/Starlette) | O(n) | ≤ 1 MB in memory, n on disk | 0 |
| 2 | Check the path (`validate_path`) and the declared size (`file.size`) | Local | O(length of path) | O(1) | 0 |
| 3 | Read the file into memory (`file.file.read(...)`) | Local | O(n) | n | 0 |
| 4 | Send it to Dropbox (`files_upload`, one HTTP request with n bytes) | **Dropbox** | O(n) network transfer | the same n bytes, no copy | **1** |
| 5 | Build the response (`FileResource`) | Local | O(1) | O(1) | 0 |

**Total:** time **O(n)**, memory **O(n)**, temporary disk **O(n)** for files over 1 MB, and **exactly 1 Dropbox call**, whatever the size.

Two extras, outside the per-request cost:
- **Token refresh.** The Dropbox client is shared by all requests. It fetches an access token with the refresh token on its first call, then again about every 4 hours: 1 extra call, not 1 per upload. Before PR #18, every request built a new client and paid this extra call each time.
- **Cache.** With `REDIS_URL` set, a successful upload also clears that path's cached metadata: one local Redis call, no Dropbox call.

## Measured

Uploads of random bytes to real Dropbox through the app (`TestClient`), on a home connection, with Python 3.13. Peak memory is Python's own allocations during the request, measured with `tracemalloc`. Dropbox calls are counted at the HTTP level.

| File size | Time | Peak memory | Dropbox calls |
| --- | --- | --- | --- |
| 1 KB | 1.16 s | 1.3 MB | 1 (`upload`) |
| 1 MB | 1.03 s | 3.2 MB | 1 (`upload`) |
| 5 MB | 1.35 s | **162.4 MB** | 1 (`upload`) |
| 20 MB | 1.77 s | **177.4 MB** | 1 (`upload`) |

Before these, the first Dropbox call after start-up made 2 calls: `token` (the refresh) and the call itself. After that, every upload was exactly 1 call.

**Time:** about 1 second is a fixed round trip to Dropbox, and the rest grows with size (about 0.75 s more for 20 MB, roughly 25–30 MB/s). Small files are dominated by latency, and large ones by bandwidth, which is the O(n) part.

**Memory:** 1 KB and 1 MB behave as expected, with a small multiple of n. The 5 MB and 20 MB rows don't: each is about **157 MB plus the file size**. See the next section.

## What the measurement found: a fixed 157 MB per upload over 1 MB

The route reads the upload with:

```python
content = file.file.read(MAX_UPLOAD_BYTES + 1)
```

For a file over 1 MB, FastAPI has already moved it to a temporary file on disk. When Python reads from a real file with `read(limit)`, it first reserves a buffer of the full `limit`, about 157 MB (150 MiB + 1), and only then shrinks it to the actual size. Files still in memory don't do this. We confirmed it in isolation with the same 5 MB of data:

| How the data is read | Peak memory |
| --- | --- |
| Kept in memory, `read(limit)` | 0 MB extra |
| **On disk, `read(limit)` (the route today)** | **157.3 MB** |
| On disk, read in 1 MB chunks | 10 MB |

So the real memory cost today is **O(n) + a fixed 157 MB for any file over 1 MB**. Three uploads of 2 MB at the same time briefly use about half a gigabyte. The Big-O is still O(n), but the constant is large enough to matter on a small server.

**Fix (follow-up):** read only what's needed. The size is almost always known up front:

```python
limit = MAX_UPLOAD_BYTES + 1 if file.size is None else min(file.size, MAX_UPLOAD_BYTES) + 1
content = file.file.read(limit)
```

When the size is unknown, read in 1 MB chunks and stop once the total passes the limit. Either way, peak memory falls back to about n.

## Why not stream the file instead

Memory could be O(1) in n if we never held the whole file, using Dropbox's upload sessions: `upload_session/start`, `append` for each chunk, then `finish`. The cost is more Dropbox calls, about n ÷ chunk size + 2, each with its own round trip, and more failure cases to handle, since any chunk can fail midway. At our 150 MB limit, a single call with the file in memory is simpler and faster. Upload sessions become necessary for files over 150 MB.
