import os


class Config:
    POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "postgres")
    POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
    POSTGRES_DB = os.environ["POSTGRES_DB"]

    # Deliberately the read-only role (readonly_role.sh), never the
    # privileged POSTGRES_USER/PASSWORD ingestion/dashboard/telegram-listener
    # use — this service can only ever SELECT, a real DB-level guarantee.
    POSTGRES_READONLY_USER = os.environ["POSTGRES_READONLY_USER"]
    POSTGRES_READONLY_PASSWORD = os.environ["POSTGRES_READONLY_PASSWORD"]

    # Shared-password login gate (see app/auth.py) — not per-user accounts,
    # a deliberate choice for this self-hosted single/small-team tool.
    APP_PASSWORD = os.environ["APP_PASSWORD"]
    APP_SECRET_KEY = os.environ["APP_SECRET_KEY"]


config = Config()
