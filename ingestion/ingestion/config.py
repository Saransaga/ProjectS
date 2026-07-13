import os


class Config:
    POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "postgres")
    POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
    POSTGRES_USER = os.environ["POSTGRES_USER"]
    POSTGRES_PASSWORD = os.environ["POSTGRES_PASSWORD"]
    POSTGRES_DB = os.environ["POSTGRES_DB"]

    REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
    REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

    TZ = os.environ.get("TZ", "Asia/Kolkata")

    # Optional: Reddit's official API (PRAW) needs a registered "script" app
    # at reddit.com/prefs/apps. Left unset, the Reddit job skips gracefully
    # rather than failing the whole ingestion run.
    REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID")
    REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET")
    REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT", "trading-data-pipeline/1.0")

    HTTP_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )


config = Config()
