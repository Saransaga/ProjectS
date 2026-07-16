"""Dispatches one inbound Telegram update to a reply — /start, /help,
/watch, /unwatch, /list, /recommend, /top, or bare free text treated as a
symbol/company lookup (the common case: a user just types "TCS" or
"reliance"). Every handler returns the reply text; handle_update owns the
actual send_message call so a delivery failure (bot blocked, HTTP 403) is
handled in exactly one place.
"""

import logging

from .. import telegram_client
from ..query.resolve import AmbiguousQueryError, resolve
from ..query.snapshot import (
    NEAR_LOW_PCT,
    latest_close,
    latest_recommendation,
    latest_recommendation_date,
    price_levels,
    stocks_near_52_week_low,
    top_dividend_yield,
    top_movers,
)
from ..upsert_telegram import add_watch, list_watchlist, mark_chat_inactive, remove_watch, upsert_chat
from .formatting import (
    format_52_week_lows,
    format_ambiguous,
    format_dividend_leaders,
    format_help,
    format_recommendation,
    format_top_buys,
    format_watchlist,
)

_TOP_N = 5

logger = logging.getLogger(__name__)


def handle_update(conn, update: dict) -> None:
    message = update.get("message")
    if not message or "text" not in message:
        return  # non-text update (photo, edited_message, channel post, ...) — nothing this bot handles

    chat = message["chat"]
    chat_id = chat["id"]
    upsert_chat(conn, chat_id, chat["type"], message.get("from", {}).get("username"))

    reply = _dispatch(conn, chat_id, message["text"].strip())
    if not reply:
        return
    try:
        telegram_client.send_message(chat_id, reply)
    except telegram_client.TelegramApiError as exc:
        if "403" in str(exc):
            mark_chat_inactive(conn, chat_id)
        logger.warning("send_message to chat %s failed: %s", chat_id, exc)


def _dispatch(conn, chat_id: int, text: str) -> str:
    if text.startswith("/start") or text.startswith("/help"):
        return format_help()
    if text.startswith("/watch"):
        return _handle_watch(conn, chat_id, text[len("/watch"):].strip())
    if text.startswith("/unwatch"):
        return _handle_unwatch(conn, chat_id, text[len("/unwatch"):].strip())
    if text.startswith("/list"):
        return format_watchlist(list_watchlist(conn, chat_id))
    if text.startswith("/recommend"):
        return _handle_recommend(conn, text[len("/recommend"):].strip())
    if text.startswith("/top"):
        return _handle_top(conn)
    if text.startswith("/52wlow"):
        return _handle_52_week_low(conn)
    if text.startswith("/dividends"):
        return _handle_dividends(conn)
    return _handle_recommend(conn, text)  # bare text: treat as a lookup


def _resolve_or_message(conn, query: str) -> tuple[dict | None, str | None]:
    if not query:
        return None, "Send a stock symbol or company name, e.g. `TCS` or `/watch HDFC Bank`."
    try:
        match = resolve(conn, query)
    except AmbiguousQueryError as exc:
        return None, format_ambiguous(exc.query, exc.candidates)
    if match is None:
        return None, f"No instrument found matching {query!r}."
    return match, None


def _handle_recommend(conn, query: str) -> str:
    match, error = _resolve_or_message(conn, query)
    if error:
        return error
    rec = latest_recommendation(conn, match["instrument_id"])
    close = latest_close(conn, match["instrument_id"])
    levels = price_levels(conn, match["instrument_id"], close["close"] if close else None)
    return format_recommendation(match, rec, close, levels)


def _handle_top(conn) -> str:
    as_of_date = latest_recommendation_date(conn)
    if as_of_date is None:
        return "No recommendations computed yet — check back after the next daily run."
    entries = top_movers(conn, as_of_date, "short", "buy", limit=_TOP_N)
    for entry in entries:
        close = latest_close(conn, entry["instrument_id"])
        entry["levels"] = price_levels(conn, entry["instrument_id"], close["close"] if close else None)
    return format_top_buys(as_of_date, entries)


def _handle_52_week_low(conn) -> str:
    entries = stocks_near_52_week_low(conn, limit=_TOP_N)
    return format_52_week_lows(entries, near_pct=NEAR_LOW_PCT)


def _handle_dividends(conn) -> str:
    entries = top_dividend_yield(conn, limit=_TOP_N)
    return format_dividend_leaders(entries)


def _handle_watch(conn, chat_id: int, query: str) -> str:
    match, error = _resolve_or_message(conn, query)
    if error:
        return error
    verb = "Added" if add_watch(conn, chat_id, match["instrument_id"]) else "Already watching"
    return f"{verb} {match['symbol']} ({match['name']})."


def _handle_unwatch(conn, chat_id: int, query: str) -> str:
    match, error = _resolve_or_message(conn, query)
    if error:
        return error
    if remove_watch(conn, chat_id, match["instrument_id"]):
        return f"Removed {match['symbol']} from your watchlist."
    return f"{match['symbol']} wasn't on your watchlist."
