"""Domain 8's Telegram push job: watchlist-change alerts (anti-spam — only
messages a chat when a watched instrument's action actually changed since
the last alert, see telegram_watchlist_alert_state) + a daily top-N
strongest-buy/sell digest to every active chat. always_force=True: this is a
push over already-computed stock_recommendations rows (must run after
RecommendationEngineJob, see scheduler.py), not a live market fetch, and
manual backfills/reruns need to work on any date.

fetch() does the actual sending (and the DB writes that record it) rather
than just reading, unlike every other job in this project — "push to
Telegram" *is* this job's side effect, there's nothing to hand a separate
_persist() step; _persist() here is a no-op that just returns the count
BaseJob logs to ingestion_log.
"""

import logging
from datetime import date

from .. import telegram_client
from ..config import config
from ..db import get_conn
from ..query.snapshot import latest_close, price_levels, top_movers
from ..telegram_bot.formatting import format_digest, format_recommendation
from ..upsert_telegram import (
    get_active_chat_ids,
    get_watchlist_alert_candidates,
    log_alert,
    mark_chat_inactive,
    upsert_alert_state,
)
from .base import BaseJob

logger = logging.getLogger(__name__)

_DIGEST_TOP_N = 5


class TelegramAlertsJob(BaseJob):
    job_name = "telegram_alerts"
    always_force = True

    def fetch(self, run_date: date) -> list[dict]:
        if not config.TELEGRAM_BOT_TOKEN:
            logger.warning("telegram_alerts: TELEGRAM_BOT_TOKEN not set, skipping")
            return []

        with get_conn() as conn:
            sent = self._send_watchlist_alerts(conn, run_date)
            sent += self._send_digest(conn, run_date)
            return sent

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        return len(rows)

    def _send_watchlist_alerts(self, conn, run_date: date) -> list[dict]:
        sent = []
        for candidate in get_watchlist_alert_candidates(conn, run_date):
            changed = (
                candidate["short_term_action"] != candidate["last_short_term_action"]
                or candidate["long_term_action"] != candidate["last_long_term_action"]
            )
            if not changed:
                continue

            match = {"symbol": candidate["symbol"], "name": candidate["name"]}
            rec = {
                "as_of_date": run_date,
                "short_term_score": candidate["short_term_score"],
                "short_term_action": candidate["short_term_action"],
                "short_term_rationale": candidate["short_term_rationale"],
                "long_term_score": candidate["long_term_score"],
                "long_term_action": candidate["long_term_action"],
                "long_term_rationale": candidate["long_term_rationale"],
            }
            close = latest_close(conn, candidate["instrument_id"])
            levels = price_levels(conn, candidate["instrument_id"], close["close"] if close else None)
            text = format_recommendation(match, rec, close, levels, show_watch_tip=False)
            delivered = self._deliver(conn, candidate["chat_id"], "WATCHLIST", candidate["instrument_id"], run_date, text)
            if not delivered:
                continue  # leave alert_state untouched so a failed send is retried next run, not silently dropped
            upsert_alert_state(
                conn,
                candidate["chat_id"],
                candidate["instrument_id"],
                candidate["short_term_action"],
                candidate["long_term_action"],
                run_date,
            )
            sent.append(candidate)
        return sent

    def _send_digest(self, conn, run_date: date) -> list[dict]:
        buys = top_movers(conn, run_date, "short", "buy", _DIGEST_TOP_N)
        sells = top_movers(conn, run_date, "short", "sell", _DIGEST_TOP_N)
        if not buys and not sells:
            return []

        for entry in buys + sells:
            close = latest_close(conn, entry["instrument_id"])
            entry["levels"] = price_levels(conn, entry["instrument_id"], close["close"] if close else None)

        text = format_digest(run_date, buys, sells)
        sent = []
        for chat_id in get_active_chat_ids(conn):
            self._deliver(conn, chat_id, "DIGEST", None, run_date, text)
            sent.append({"chat_id": chat_id, "scope": "DIGEST"})
        return sent

    def _deliver(self, conn, chat_id: int, scope: str, instrument_id: int | None, run_date: date, text: str) -> bool:
        try:
            telegram_client.send_message(chat_id, text)
            log_alert(conn, chat_id, scope, instrument_id, run_date, text, "SENT", None)
            return True
        except telegram_client.TelegramApiError as exc:
            log_alert(conn, chat_id, scope, instrument_id, run_date, text, "FAILED", str(exc))
            if "403" in str(exc):
                mark_chat_inactive(conn, chat_id)
            logger.warning("telegram_alerts: send to chat %s failed: %s", chat_id, exc)
            return False
