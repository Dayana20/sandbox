"""Dropbox client construction without application-global configuration."""

import os
from collections.abc import Mapping

import dropbox
from cloud_storage_api.errors import InvalidRequestError


def create_dropbox_client(
    *,
    app_key: str,
    app_secret: str,
    refresh_token: str,
) -> dropbox.Dropbox:
    """Create a refresh-token Dropbox SDK client from explicit credentials."""
    credentials = {
        "DROPBOX_APP_KEY": app_key,
        "DROPBOX_APP_SECRET": app_secret,
        "DROPBOX_REFRESH_TOKEN": refresh_token,
    }
    missing = [name for name, value in credentials.items() if not value or not value.strip()]
    if missing:
        raise InvalidRequestError(
            "Dropbox refresh-token configuration is missing: " + ", ".join(missing)
        )

    return dropbox.Dropbox(
        oauth2_refresh_token=refresh_token,
        app_key=app_key,
        app_secret=app_secret,
    )


def create_dropbox_client_from_env(
    environ: Mapping[str, str] | None = None,
) -> dropbox.Dropbox:
    """Create a client from three environment variables.

    No ``.env`` file is loaded. The caller controls how its process environment
    is populated and may pass a mapping explicitly for tests or configuration
    systems that do not mutate ``os.environ``.
    """
    values = os.environ if environ is None else environ
    return create_dropbox_client(
        app_key=values.get("DROPBOX_APP_KEY", ""),
        app_secret=values.get("DROPBOX_APP_SECRET", ""),
        refresh_token=values.get("DROPBOX_REFRESH_TOKEN", ""),
    )
