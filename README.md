# Document Storage Agent

FastAPI service for storing and retrieving documents through pluggable storage providers. Dropbox is the first provider.

This branch, `yashwanth`, is the start of that service.

## What is in place

- A FastAPI application (`app/main.py`) that loads settings and mounts the API router.
- `GET /health`, which returns `{"status": "ok"}`.
- Settings loaded from a local `.env` file (`APP_NAME` and the Dropbox credentials).
- A Dropbox client factory (`app/providers/dropbox/client.py`) that authenticates with `DROPBOX_ACCESS_TOKEN`.
- A local script that checks the Dropbox connection by calling `users_get_current_account()`.
- A pytest test for the health endpoint.

`app/models/` is reserved for domain models. Document upload, download, and listing are still to be built. The Dropbox app key and secret are loaded with the other settings; the client currently uses the access token.

## Project layout

```
app/
├── main.py                 # FastAPI entry point
├── api/
│   ├── router.py           # Mounts route modules
│   └── routes/health.py    # GET /health
├── core/config.py          # Environment settings
├── models/                 # Domain models
└── providers/dropbox/      # Dropbox client
scripts/verify_dropbox.py   # Local Dropbox connection check
tests/test_health.py        # Health endpoint test
.env.example                # Environment variable template
requirements.txt
```

## Setup

Python 3.10 or newer.

```powershell
python -m venv doc
.\doc\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

```bash
python -m venv doc
source doc/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env` on your machine. Keep that file local. It is listed in `.gitignore`.

| Variable | Purpose |
| --- | --- |
| `APP_NAME` | Name shown by the API |
| `DROPBOX_APP_KEY` | Dropbox app key |
| `DROPBOX_APP_SECRET` | Dropbox app secret |
| `DROPBOX_ACCESS_TOKEN` | Token used to create the Dropbox client |

## Run the API

From the project root, with the virtual environment active:

```powershell
uvicorn app.main:app --reload
```

Health check: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

## Tests

```powershell
pytest
```

`tests/test_health.py` calls `GET /health` and expects status `200` and `{"status": "ok"}`.

## Verify Dropbox

Set `DROPBOX_ACCESS_TOKEN` in `.env`, then run this from the project root:

```powershell
python -m scripts.verify_dropbox
```

The script creates a Dropbox client and calls `users_get_current_account()`. A working token prints a success message, the account ID, and the account display name. A missing token raises `DROPBOX_ACCESS_TOKEN is not configured`.
