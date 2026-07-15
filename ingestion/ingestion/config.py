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

    # Optional: a bot token from @BotFather (api.telegram.org/bot<token>/...).
    # Left unset, TelegramAlertsJob and telegram_listener.py both log a clear
    # error and no-op rather than crashing at import. Deliberately no
    # TELEGRAM_CHAT_ID: the broadcast audience is entirely DB-driven
    # (telegram_chats, populated as chats message the bot), never a single
    # hardcoded chat, since multi-user support is a requirement from day one.
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

    HTTP_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )


config = Config()
