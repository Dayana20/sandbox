from dropbox import DropboxOAuth2FlowNoRedirect

from app.core.config import settings


def main() -> None:
    if not settings.dropbox_app_key or not settings.dropbox_app_secret:
        raise SystemExit(
            "Set DROPBOX_APP_KEY and DROPBOX_APP_SECRET in .env first"
        )

    # "offline" asks Dropbox for a refresh token that does not expire
    flow = DropboxOAuth2FlowNoRedirect(
        settings.dropbox_app_key,
        consumer_secret=settings.dropbox_app_secret,
        token_access_type="offline",
    )

    print("1. Open this URL and click Allow:")
    print(flow.start())
    code = input("2. Paste the code Dropbox shows you: ").strip()

    result = flow.finish(code)

    print("3. Add this line to .env:")
    print(f"DROPBOX_REFRESH_TOKEN={result.refresh_token}")


if __name__ == "__main__":
    main()
