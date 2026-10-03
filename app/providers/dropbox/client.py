import dropbox

from app.core.config import settings


def create_dropbox_client() -> dropbox.Dropbox:
    if not settings.dropbox_access_token:
        raise RuntimeError(
            "DROPBOX_ACCESS_TOKEN is not configured"
        )

    return dropbox.Dropbox(
        oauth2_access_token=settings.dropbox_access_token
    )