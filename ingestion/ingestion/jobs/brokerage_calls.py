import logging
import time
from datetime import date

from .. import moneycontrol_client
from ..brokerage.classify import classify_rating
from ..db import get_conn
from ..upsert_brokerage import bulk_upsert_brokerage_calls, bulk_upsert_rating_change_events
from .base import BaseJob

logger = logging.getLogger(__name__)

_INTER_SYMBOL_DELAY_SECONDS = 0.3
_SOURCE = "MONEYCONTROL"

# Most bullish first — ranks a rating_bucket for UPGRADE/DOWNGRADE detection.
# Moving toward STRONG_BUY is an upgrade, moving toward STRONG_SELL is a
# downgrade (see brokerage/consensus.py's _BUCKET_ORDER for the same ordering
# used by the downstream consensus job).
_RATING_RANK = {"STRONG_SELL": 0, "SELL": 1, "HOLD": 2, "BUY": 3, "STRONG_BUY": 4}


class BrokerageCallsJob(BaseJob):
    """Domain 5's primary feed: Moneycontrol's per-stock "Broker Research"
    section (see moneycontrol_client.py for what's verified live there),
    walked across every active NSE equity to build brokerage_calls +
    rating_change_events.

    SLOW BY DESIGN: this iterates ~2,000+ instruments, one HTTP page fetch
    each plus a rate-limit sleep between them (same sequential-with-sleep
    convention as financial_results.py's _INTER_SYMBOL_DELAY_SECONDS,
    deliberately not parallelized/threaded — this codebase's established
    external-fetch style is sequential, not concurrent, and this job
    intentionally doesn't introduce a new pattern). A full run is expected to
    take on the order of tens of minutes; that's accepted, not a bug.

    No always_force: like financial_results.py (also a real-time/current-
    state feed, not a point-in-time historical view), this is meant to run
    "daily after market close" per the domain spec, which only makes sense
    on an actual trading day (there's no "after market close" event on a day
    the market never opened) — so is_trading_day()'s weekday/holiday gate is
    exactly the schedule this job wants, and always_force isn't needed.

    Symbol resolution is cached in moneycontrol_instrument_map so only
    previously-unresolved instruments pay the extra resolve_stock() round
    trip; a symbol that fails to resolve (rare-symbol mismatch, moneycontrol
    downtime, etc.) is logged and skipped for this run rather than failing
    the whole job — it'll simply be retried unresolved on the next run.
    """

    job_name = "brokerage_calls"

    def fetch(self, run_date: date) -> list[dict]:
        rows: list[dict] = []
        with get_conn() as conn:
            for instrument_id, symbol in self._active_equities(conn):
                page_url = self._resolve_page_url(conn, instrument_id, symbol)
                if page_url is None:
                    continue

                try:
                    raw_calls = moneycontrol_client.fetch_broker_research(page_url)
                except Exception:
                    logger.warning("broker-research fetch failed for %s", symbol, exc_info=True)
                    time.sleep(_INTER_SYMBOL_DELAY_SECONDS)
                    continue

                if raw_calls:
                    rows.extend(self._build_rows(conn, instrument_id, raw_calls))

                time.sleep(_INTER_SYMBOL_DELAY_SECONDS)
        return rows

    def _active_equities(self, conn) -> list[tuple[int, str]]:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT instrument_id, symbol FROM instruments "
                "WHERE exchange = 'NSE' AND instrument_type = 'EQUITY' AND is_active"
            )
            return cur.fetchall()

    def _resolve_page_url(self, conn, instrument_id: int, symbol: str) -> str | None:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT mc_page_url FROM moneycontrol_instrument_map WHERE instrument_id = %s",
                (instrument_id,),
            )
            row = cur.fetchone()
        if row is not None:
            return row[0]

        try:
            resolved = moneycontrol_client.resolve_stock(symbol)
        except Exception:
            logger.warning("moneycontrol resolve_stock failed for %s", symbol, exc_info=True)
            return None
        if resolved is None:
            logger.warning("moneycontrol resolve_stock found no exact-symbol match for %s", symbol)
            return None

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO moneycontrol_instrument_map (instrument_id, mc_sc_id, mc_page_url)
                VALUES (%s, %s, %s)
                ON CONFLICT (instrument_id) DO UPDATE SET
                    mc_sc_id = EXCLUDED.mc_sc_id,
                    mc_page_url = EXCLUDED.mc_page_url,
                    resolved_at = now()
                """,
                (instrument_id, resolved["sc_id"], resolved["page_url"]),
            )
        return resolved["page_url"]

    def _existing_calls(self, conn, instrument_id: int) -> tuple[dict, set]:
        """Snapshot of this instrument's already-ingested MONEYCONTROL calls,
        taken once per instrument before processing this run's fresh page —
        used both to skip calls already seen and to find each brokerage's
        immediately-prior call for rating-change detection."""
        with conn.cursor() as cur:
            cur.execute(
                "SELECT brokerage_name, call_date, rating_bucket, target_price "
                "FROM brokerage_calls WHERE instrument_id = %s AND source = %s",
                (instrument_id, _SOURCE),
            )
            existing_rows = cur.fetchall()

        by_brokerage: dict[str, list[tuple]] = {}
        seen_dates: set[tuple[str, date]] = set()
        for brokerage_name, call_date, rating_bucket, target_price in existing_rows:
            by_brokerage.setdefault(brokerage_name, []).append((call_date, rating_bucket, target_price))
            seen_dates.add((brokerage_name, call_date))
        return by_brokerage, seen_dates

    def _prior_call(self, by_brokerage: dict, brokerage_name: str, call_date: date):
        candidates = [c for c in by_brokerage.get(brokerage_name, []) if c[0] < call_date]
        if not candidates:
            return None
        return max(candidates, key=lambda c: c[0])

    def _build_rows(self, conn, instrument_id: int, raw_calls: list[dict]) -> list[dict]:
        by_brokerage, seen_dates = self._existing_calls(conn, instrument_id)

        rows: list[dict] = []
        for raw in raw_calls:
            brokerage_name = raw["brokerage_name"]
            call_date = raw["call_date"]

            if (brokerage_name, call_date) in seen_dates:
                continue  # already ingested this exact call, nothing new

            rating_bucket = classify_rating(raw["raw_rating"])
            rows.append(
                {
                    "_kind": "call",
                    "instrument_id": instrument_id,
                    "brokerage_name": brokerage_name,
                    "call_date": call_date,
                    "raw_rating": raw["raw_rating"],
                    "rating_bucket": rating_bucket,
                    "reco_price": raw.get("reco_price"),
                    "target_price": raw.get("target_price"),
                    "report_url": raw.get("report_url"),
                    "source": _SOURCE,
                }
            )

            event = self._build_event(instrument_id, brokerage_name, call_date, rating_bucket, raw.get("target_price"), by_brokerage)
            if event is not None:
                rows.append(event)

        return rows

    def _build_event(
        self,
        instrument_id: int,
        brokerage_name: str,
        call_date: date,
        rating_bucket: str | None,
        target_price,
        by_brokerage: dict,
    ) -> dict | None:
        # rating_change_events.new_rating_bucket is NOT NULL — a raw_rating
        # this codebase's vocabulary doesn't recognize can't produce an event
        # at all, regardless of change_type (see brokerage/classify.py).
        if rating_bucket is None:
            return None

        prior = self._prior_call(by_brokerage, brokerage_name, call_date)
        if prior is None:
            return {
                "_kind": "event",
                "instrument_id": instrument_id,
                "brokerage_name": brokerage_name,
                "event_date": call_date,
                "change_type": "INITIATED",
                "previous_rating_bucket": None,
                "new_rating_bucket": rating_bucket,
                "previous_target_price": None,
                "new_target_price": target_price,
                "source": _SOURCE,
            }

        _prior_date, prior_bucket, prior_target = prior
        if prior_bucket is None:
            # A prior call exists but was never classified (unrecognized
            # raw_rating at the time) — no reliable basis to say which
            # direction the rating moved, so skip emitting an event rather
            # than guess (same "fail clearly, don't guess" spirit as
            # brokerage/classify.py itself).
            return None

        if rating_bucket == prior_bucket:
            change_type = "REITERATED"
        elif _RATING_RANK[rating_bucket] > _RATING_RANK[prior_bucket]:
            change_type = "UPGRADE"
        else:
            change_type = "DOWNGRADE"

        return {
            "_kind": "event",
            "instrument_id": instrument_id,
            "brokerage_name": brokerage_name,
            "event_date": call_date,
            "change_type": change_type,
            "previous_rating_bucket": prior_bucket,
            "new_rating_bucket": rating_bucket,
            "previous_target_price": prior_target,
            "new_target_price": target_price,
            "source": _SOURCE,
        }

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        calls = [{k: v for k, v in r.items() if k != "_kind"} for r in rows if r["_kind"] == "call"]
        events = [{k: v for k, v in r.items() if k != "_kind"} for r in rows if r["_kind"] == "event"]

        with get_conn() as conn:
            call_count = bulk_upsert_brokerage_calls(conn, calls)
            bulk_upsert_rating_change_events(conn, events)
        return call_count
