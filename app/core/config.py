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

    # One Redis for both features. Metadata caching is on only when this is
    # set. Uploads that send an Idempotency-Key are refused (503) without it.
    redis_url: str | None = os.getenv(
        "REDIS_URL"
    )

    metadata_cache_ttl_seconds: int = int(
        os.getenv("METADATA_CACHE_TTL_SECONDS", "60")
    )

    # How long an Idempotency-Key is remembered. Must be a positive number.
    idempotency_ttl_seconds: int = int(
        os.getenv("IDEMPOTENCY_TTL_SECONDS", "86400")
    )


settings = Settings()
