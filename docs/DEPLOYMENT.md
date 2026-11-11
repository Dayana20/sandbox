# Deployment: setup and teardown

How the Document Storage API is run on Oracle Cloud (OCI), how to deploy a new version, and how to take everything down again.

## What runs where

| Piece | Where | File |
| --- | --- | --- |
| Container image | Built on the VM from this repo | `Dockerfile` (Python 3.12, runs as a non-root user) |
| Service definition | The VM | `compose.yaml` (one `api` service, restarts unless stopped, 650 MB memory limit) |
| Dropbox credentials | `.env` on the VM only | never in the image (`.dockerignore` excludes `.env`) or in git |
| Deploy pipeline | GitHub Actions | `.github/workflows/deploy-oci.yml` |
| Test pipeline | GitHub Actions | `.github/workflows/ci.yml` (tests, lint, types, Docker build, shared conformance suite) |

The container listens on port 8000, published only on the VM's `127.0.0.1`. Liveness checks use `GET /health`, which never calls Dropbox, so a Dropbox outage does not restart the container. `GET /health/provider` checks Dropbox itself.

## Setup (once)

### 1. The VM

1. Create an OCI compute instance (Ubuntu) and add your SSH public key.
2. On the VM, install Docker with the Compose plugin and `git`:
   ```bash
   sudo apt-get update
   sudo apt-get install -y git docker.io docker-compose-v2
   ```
3. Clone the repo into the deploy user's home and switch to the deployment branch:
   ```bash
   git clone https://github.com/Dayana20/sandbox.git ~/sandbox
   cd ~/sandbox
   git switch hw2-milestone3
   ```
4. Create `~/sandbox/.env` with the Dropbox credentials (same names as `.env.example`), readable only by the deploy user:
   ```bash
   cp .env.example .env
   chmod 600 .env
   # fill in DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN
   ```
   Leave `REDIS_URL` empty: the cache and idempotency are optional and not deployed.
5. Let the deploy user run Docker Compose with `sudo` without a password (the pipeline uses `sudo -n docker compose ...`).
6. First start, by hand:
   ```bash
   sudo docker compose up -d --build api
   curl -fsS http://127.0.0.1:8000/health            # {"status":"ok"}
   curl -fsS http://127.0.0.1:8000/health/provider   # {"status":"ok"} if Dropbox works
   ```

### 2. GitHub

In the repo's **Settings → Environments**, create an environment named `production`, and add these secrets to it:

| Secret | Value |
| --- | --- |
| `OCI_HOST` | The VM's public IP or hostname |
| `OCI_USER` | The deploy user on the VM |
| `OCI_SSH_PRIVATE_KEY` | A private key whose public key is in that user's `~/.ssh/authorized_keys`. Use a key made only for deploys |
| `OCI_KNOWN_HOSTS` | The VM's host key line, from `ssh-keyscan <OCI_HOST>` |

For the conformance job in CI, add these under **Settings → Secrets and variables → Actions**: `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`.

## Deploy a new version

1. Merge the change into `hw2-milestone3` through a reviewed PR, and wait for CI to pass.
2. Tag that commit and push the tag:
   ```bash
   git switch hw2-milestone3 && git pull
   git tag deploy-oci-$(date +%Y%m%d-%H%M)
   git push origin --tags
   ```
3. The **Deploy Document Storage API to OCI** workflow then SSHes into the VM and:
   - refuses to run if the VM's checkout has local changes, `.env` is missing, or `hw2-milestone3` moved since the tag
   - fast-forwards the VM to that commit, rebuilds the image and restarts only the `api` container
   - waits up to 90 seconds for `GET /health`, and fails the run if it never answers
4. Check it: the workflow run is green, and on the VM `curl -fsS http://127.0.0.1:8000/health/provider` returns `{"status":"ok"}`.

**Roll back:** the workflow only deploys the commit `hw2-milestone3` currently points at, so the cleanest rollback is a revert PR followed by a new tag. In an emergency, on the VM:
```bash
cd ~/sandbox
git switch --detach <good-commit>
sudo docker compose up -d --build api
```

## Teardown

1. **Stop and remove the service** on the VM:
   ```bash
   cd ~/sandbox
   sudo docker compose down --rmi local
   ```
2. **Remove the credentials** from the VM: `rm ~/sandbox/.env`.
3. **Delete the VM** (and its boot volume) in the OCI console: Compute → Instances → the instance → Terminate, with "Permanently delete the attached boot volume" ticked. Delete any public IP, VCN or security list rules created only for it.
4. **Remove access from GitHub:** delete the `production` environment secrets (`OCI_HOST`, `OCI_USER`, `OCI_SSH_PRIVATE_KEY`, `OCI_KNOWN_HOSTS`), and delete the deploy key's public half from anywhere else it was added.
5. **Revoke the Dropbox access** if this deployment had its own credentials: Dropbox App Console → the app → revoke the refresh token, or remove the app from the account. Then delete the Dropbox repo secrets used by CI if the conformance job is no longer needed.
6. **Clean up test files** left in the Dropbox app folder, if any run was interrupted: folders named `/conformance-<random>` and `/integration-tests/...`. Normal runs delete their own.
