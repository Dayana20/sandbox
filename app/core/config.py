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

    dropbox_refresh_token: str | None = os.getenv(
        "DROPBOX_REFRESH_TOKEN"
    )

    dropbox_app_key: str | None = os.getenv(
        "DROPBOX_APP_KEY"
    )

    dropbox_app_secret: str | None = os.getenv(
        "DROPBOX_APP_SECRET"
    )

    # Upload idempotency needs Redis. Without REDIS_URL, uploads that send an
    # Idempotency-Key are refused (503). Uploads without a key never use Redis.
    redis_url: str | None = os.getenv(
        "REDIS_URL"
    )

    # How long an Idempotency-Key is remembered. Must be a positive number.
    idempotency_ttl_seconds: int = int(
        os.getenv("IDEMPOTENCY_TTL_SECONDS", "86400")
    )


settings = Settings()