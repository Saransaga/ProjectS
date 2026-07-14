"""Thin wrapper over the Telegram Bot HTTP API — plain `requests`, no SDK,
same hand-rolled-client convention as moneycontrol_client.py/
tickertape_client.py/rss_client.py (this project deliberately avoids heavy
per-integration SDKs, see requirements.txt).

get_updates' `timeout` param is Telegram's own long-polling timeout: the
request blocks server-side for up to that many seconds waiting for a new
message before returning an empty result, rather than the caller polling
tightly in a loop. A `requests.exceptions.ReadTimeout`/`ConnectionError` on
an idle period is therefore expected steady-state behavior of long-polling,
not an exceptional failure — see telegram_bot/ (telegram_listener.py) for
how the poll loop handles that; this module itself doesn't retry get_updates
(a caller-level backoff loop owns that decision, since "wait and re-poll" is
the correct response, not "retry the same call immediately").
"""

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import config

_BASE = "https://api.telegram.org/bot{token}"


class TelegramNotConfiguredError(Exception):
    """TELEGRAM_BOT_TOKEN is unset — caller should degrade gracefully, not crash."""


class TelegramApiError(Exception):
    """Non-2xx or ok:false response from the Telegram Bot API."""


def _require_token() -> str:
    if not config.TELEGRAM_BOT_TOKEN:
        raise TelegramNotConfiguredError("TELEGRAM_BOT_TOKEN is not set")
    return config.TELEGRAM_BOT_TOKEN


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(requests.RequestException),
    reraise=True,
)
def _call(method: str, params: dict | None = None, timeout: int = 15) -> dict:
    token = _require_token()
    url = f"{_BASE.format(token=token)}/{method}"
    resp = requests.get(url, params=params or {}, timeout=timeout)
    try:
        payload = resp.json()
    except ValueError as exc:
        raise TelegramApiError(f"{method}: non-JSON response (status {resp.status_code})") from exc

    if resp.status_code != 200 or not payload.get("ok"):
        raise TelegramApiError(
            f"{method}: status={resp.status_code} description={payload.get('description')}"
        )
    return payload["result"]


def get_me() -> dict:
    return _call("getMe")


def send_message(chat_id: int, text: str, parse_mode: str = "Markdown") -> dict:
    """Telegram caps a single message at 4096 UTF-16 code units — callers
    (telegram_bot/formatting.py) are responsible for staying under that;
    this function doesn't truncate or split, so an oversized text raises
    TelegramApiError from Telegram's own 400 response."""
    return _call(
        "sendMessage",
        {"chat_id": chat_id, "text": text, "parse_mode": parse_mode, "disable_web_page_preview": True},
    )


def get_updates(offset: int | None = None, timeout: int = 30) -> list[dict]:
    """timeout here is Telegram's long-poll window (see module docstring);
    the HTTP request timeout is set a little above it so the network call
    itself doesn't time out before Telegram's own long-poll does."""
    params = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    return _call("getUpdates", params, timeout=timeout + 10)
