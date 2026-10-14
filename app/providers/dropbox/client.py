import dropbox

from app.core.config import settings


def dropbox_credentials_configured() -> bool:
    return bool(
        settings.dropbox_refresh_token
        or settings.dropbox_access_token
    )


def create_dropbox_client() -> dropbox.Dropbox:
    # A refresh token never expires. The SDK uses it to get a new
    # short-lived access token whenever the current one runs out.
    if settings.dropbox_refresh_token:
        if not settings.dropbox_app_key or not settings.dropbox_app_secret:
            raise RuntimeError(
                "DROPBOX_REFRESH_TOKEN needs DROPBOX_APP_KEY "
                "and DROPBOX_APP_SECRET"
            )

        return dropbox.Dropbox(
            oauth2_refresh_token=settings.dropbox_refresh_token,
            app_key=settings.dropbox_app_key,
            app_secret=settings.dropbox_app_secret,
        )

    # Fallback: a token from the App Console, which expires after about 4 hours
    if settings.dropbox_access_token:
        return dropbox.Dropbox(
            oauth2_access_token=settings.dropbox_access_token
        )

    raise RuntimeError(
        "Dropbox is not configured. Set DROPBOX_REFRESH_TOKEN, "
        "DROPBOX_APP_KEY and DROPBOX_APP_SECRET in .env"
    )
