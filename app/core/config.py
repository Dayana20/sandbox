import os

from dotenv import load_dotenv


load_dotenv()


class Settings:
    app_name: str = os.getenv(
        "APP_NAME",
        "Document Storage Service",
    )

    dropbox_access_token: str | None = os.getenv(
        "DROPBOX_ACCESS_TOKEN"
    )

    dropbox_app_key: str | None = os.getenv(
        "DROPBOX_APP_KEY"
    )

    dropbox_app_secret: str | None = os.getenv(
        "DROPBOX_APP_SECRET"
    )


settings = Settings()