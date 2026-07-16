"""Turns each day's stock_recommendations short-term calls into a trackable
"position": snapshots the same target/stop the Telegram bot would have shown
that day (query/snapshot.py::price_levels + recommendation/price_levels.py's
shared resolve_price_targets), then walks ohlcv_daily forward on every run to
see whether price has since touched the target, the stop, or neither before
the call expires. See init.sql's recommendation_outcomes comment for the
schema and the "why trading_days_elapsed instead of a fixed expiry date"
rationale.

Only short-term calls are tracked: long_term_action has no natural
target/stop (support/resistance and ATR are technical, short-horizon
concepts) — see recommendation/long_term.py, which has no equivalent to
short_term.py's price-level inputs.

always_force=True: like RecommendationEngineJob, this is a recompute over
already-ingested data (today's fresh stock_recommendations row plus however
much ohlcv_daily history has landed since each open call started), not a live
market fetch.
"""

import logging
from datetime import date, timedelta

from ..db import get_conn
from ..query.snapshot import latest_close, price_levels
from ..recommendation.price_levels import resolve_price_targets
from ..recommendation.rationale_text import dominant_component_name
from ..upsert_outcomes import bulk_insert_recommendation_outcomes, bulk_update_resolved_outcomes
from .base import BaseJob

logger = logging.getLogger(__name__)

_TRACKED_ACTIONS = ("STRONG_BUY", "BUY", "SELL", "STRONG_SELL")
_BULLISH_ACTIONS = ("STRONG_BUY", "BUY")

# Short-term components already work over ~10-day windows
# (recommendation_engine.py's _SIGNAL_EVENTS_WINDOW_DAYS=10) — 15 trading days
# gives a call room to play out while staying meaningfully "short-term".
_EXPIRY_TRADING_DAYS = 15


class RecommendationOutcomesJob(BaseJob):
    job_name = "recommendation_outcomes"
    always_force = True

    def fetch(self, run_date: date) -> list[dict]:
        with get_conn() as conn:
            new_rows = self._fetch_new_calls(conn, run_date)
        return new_rows

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        with get_conn() as conn:
            inserted = bulk_insert_recommendation_outcomes(conn, rows)
            resolved = self._resolve_open_positions(conn, run_date)
        return inserted + resolved

    def _fetch_new_calls(self, conn, run_date: date) -> list[dict]:
        """Every instrument with a fresh, actionable short-term call today
        that isn't already being tracked (idempotent against reruns of the
        same date)."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.instrument_id, r.short_term_action, r.short_term_rationale
                FROM stock_recommendations r
                WHERE r.as_of_date = %s
                  AND r.short_term_action = ANY(%s)
                  AND NOT EXISTS (
                      SELECT 1 FROM recommendation_outcomes o
                      WHERE o.instrument_id = r.instrument_id
                        AND o.as_of_date = r.as_of_date
                        AND o.horizon = 'short'
                  )
                """,
                (run_date, list(_TRACKED_ACTIONS)),
            )
            candidates = cur.fetchall()

        rows = []
        for instrument_id, action, rationale in candidates:
            close = latest_close(conn, instrument_id)
            if close is None or close["close"] is None:
                continue  # no OHLCV yet for this instrument -- nothing to snapshot an entry price from
            entry_close = close["close"]
            levels = price_levels(conn, instrument_id, entry_close)
            resolved = resolve_price_targets(action, levels)
            target, stop = resolved["target"], resolved["stop"]

            rows.append({
                "instrument_id": instrument_id,
                "as_of_date": run_date,
                "horizon": "short",
                "action": action,
                "dominant_component": dominant_component_name(rationale),
                "entry_close": entry_close,
                "target_price": target["price"] if target else None,
                "target_is_projected": bool(target and target.get("projected")),
                "stop_price": stop["price"] if stop else None,
                "stop_is_projected": bool(stop and stop.get("projected")),
                "atr_14_at_entry": levels.get("atr_14") if levels else None,
                "last_checked_date": run_date,
            })
        return rows

    def _resolve_open_positions(self, conn, run_date: date) -> int:
        """Walks every OPEN call's ohlcv_daily history forward from its
        last_checked_date to run_date, day by day, checking for a target/stop
        touch or expiry. A call opened today (last_checked_date == run_date)
        has nothing to walk yet — naturally skipped by the date range."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT instrument_id, as_of_date, horizon, action, target_price, stop_price,
                       trading_days_elapsed, last_checked_date
                FROM recommendation_outcomes
                WHERE status = 'OPEN' AND last_checked_date < %s
                """,
                (run_date,),
            )
            open_positions = cur.fetchall()

        updates = []
        for (
            instrument_id, as_of_date, horizon, action, target_price, stop_price,
            trading_days_elapsed, last_checked_date,
        ) in open_positions:
            target_price = float(target_price) if target_price is not None else None
            stop_price = float(stop_price) if stop_price is not None else None
            bullish = action in _BULLISH_ACTIONS

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT trade_date, high, low, close FROM ohlcv_daily
                    WHERE instrument_id = %s AND trade_date > %s AND trade_date <= %s
                    ORDER BY trade_date ASC
                    """,
                    (instrument_id, last_checked_date, run_date),
                )
                bars = cur.fetchall()

            status, resolved_date, resolved_close = "OPEN", None, None
            days_elapsed = trading_days_elapsed
            for trade_date, high, low, close in bars:
                days_elapsed += 1
                high, low, close = float(high), float(low), float(close)
                # Same-day target+stop touch is a documented conservative
                # tie-break: a daily bar can't tell us which was touched
                # first intraday, so treat it as the stop having hit.
                hit_target = target_price is not None and (
                    (bullish and high >= target_price) or (not bullish and low <= target_price)
                )
                hit_stop = stop_price is not None and (
                    (bullish and low <= stop_price) or (not bullish and high >= stop_price)
                )
                if hit_stop:
                    status, resolved_date, resolved_close = "HIT_STOP", trade_date, close
                    break
                if hit_target:
                    status, resolved_date, resolved_close = "HIT_TARGET", trade_date, close
                    break
                if days_elapsed >= _EXPIRY_TRADING_DAYS:
                    status, resolved_date, resolved_close = "EXPIRED", trade_date, close
                    break

            updates.append({
                "instrument_id": instrument_id,
                "as_of_date": as_of_date,
                "horizon": horizon,
                "status": status,
                "trading_days_elapsed": days_elapsed,
                "resolved_date": resolved_date,
                "resolved_close": resolved_close,
                "last_checked_date": run_date,
            })

        return bulk_update_resolved_outcomes(conn, updates)
