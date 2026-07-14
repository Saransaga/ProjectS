"""Daily recompute of consensus_ratings from Domain 5's own brokerage_calls
table, cross-checked (best-effort, optional) against Tickertape's
server-rendered "Analyst Ratings & Forecast" card.

always_force=True: this is a recompute over already-ingested data (like
FundamentalRatiosJob), not a live market feed — it's meant to run daily
after market close per the domain spec ("Consensus ratings & targets: Daily
after market close"), which may land on a weekend/holiday depending on how
the scheduler cron is set up, and shouldn't be skipped by
is_trading_day()'s weekday/holiday gate in that case. Wiring the actual cron
schedule is left to scheduler.py, out of scope here.

KNOWN LIMITATION — Tickertape slug resolution (deliberately deferred):
Tickertape's own symbol-search API is IP-blocked from this environment (see
tickertape_client.py), so there is no reliable way to resolve an NSE symbol
to its Tickertape slug_id in this phase. This job instead guesses a slug via
tickertape_client.guess_slug(symbol, name) and treats a wrong guess (404, or
a page that happens to load but isn't the right stock) the same as "no
Tickertape data available" — tickertape_pct_buy/tickertape_analyst_count are
simply left NULL. This means Tickertape coverage in consensus_ratings will
be incomplete and occasionally silently wrong (if a guessed slug happens to
resolve to a *different* real stock with the same name pattern) — a full
fix requires solving general-purpose slug resolution (e.g. scraping
Tickertape's sitemap), not attempted here. The brokerage_calls-derived
fields (num_analysts, avg_target_price, consensus_rating_bucket,
implied_upside_pct) do NOT depend on Tickertape at all and are always
computed/persisted regardless of whether the Tickertape guess succeeds.
"""

import logging
from datetime import date, timedelta

from ..brokerage.consensus import compute_consensus_bucket
from ..db import get_conn
from ..tickertape_client import TickertapeFetchError, fetch_analyst_consensus, guess_slug
from ..upsert_consensus import bulk_upsert_consensus_ratings
from .base import BaseJob

logger = logging.getLogger(__name__)

_TRAILING_DAYS = 365


class ConsensusRatingsJob(BaseJob):
    job_name = "consensus_ratings"
    always_force = True

    def fetch(self, run_date: date) -> list[dict]:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT instrument_id FROM brokerage_calls")
                instrument_ids = [row[0] for row in cur.fetchall()]

            results = []
            for instrument_id in instrument_ids:
                calls = self._trailing_calls(conn, instrument_id, run_date)
                if not calls:
                    continue

                target_prices = [c["target_price"] for c in calls if c["target_price"] is not None]
                avg_target_price = sum(target_prices) / len(target_prices) if target_prices else None
                latest_close = self._latest_close(conn, instrument_id)

                row = {
                    "instrument_id": instrument_id,
                    "as_of_date": run_date,
                    "num_analysts": len(calls),
                    "avg_target_price": avg_target_price,
                    "consensus_rating_bucket": compute_consensus_bucket(
                        [c["rating_bucket"] for c in calls]
                    ),
                    "implied_upside_pct": self._implied_upside(avg_target_price, latest_close),
                    "tickertape_pct_buy": None,
                    "tickertape_analyst_count": None,
                }

                tt = self._tickertape_enrichment(conn, instrument_id)
                if tt is not None:
                    row["tickertape_pct_buy"] = tt["perc_buy_reco"]
                    row["tickertape_analyst_count"] = tt["total_reco"]

                results.append(row)
        return results

    def _trailing_calls(self, conn, instrument_id: int, run_date: date) -> list[dict]:
        """One row per brokerage — its most recent call within the trailing
        12-month window — since an older call from a brokerage that has
        since updated its view is superseded, not an additional independent
        opinion. Same DISTINCT ON dedup pattern as
        FundamentalRatiosJob._latest_quarters."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT brokerage_name, rating_bucket, target_price
                FROM (
                    SELECT DISTINCT ON (brokerage_name) brokerage_name, rating_bucket, target_price
                    FROM brokerage_calls
                    WHERE instrument_id = %s AND call_date >= %s
                    ORDER BY brokerage_name, call_date DESC
                ) recent
                """,
                (instrument_id, run_date - timedelta(days=_TRAILING_DAYS)),
            )
            rows = cur.fetchall()
        return [
            {
                "brokerage_name": r[0],
                "rating_bucket": r[1],
                "target_price": None if r[2] is None else float(r[2]),
            }
            for r in rows
        ]

    def _latest_close(self, conn, instrument_id: int) -> float | None:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT close FROM ohlcv_daily WHERE instrument_id = %s ORDER BY trade_date DESC LIMIT 1",
                (instrument_id,),
            )
            row = cur.fetchone()
            return float(row[0]) if row else None

    def _implied_upside(self, avg_target_price: float | None, latest_close: float | None) -> float | None:
        if avg_target_price is None or not latest_close:
            return None
        return (avg_target_price - latest_close) / latest_close * 100

    def _tickertape_enrichment(self, conn, instrument_id: int) -> dict | None:
        """Best-effort only — see module docstring re: slug-resolution
        limitation. Any failure (bad guess -> 404, transport error, or the
        stock genuinely having no Tickertape coverage) is swallowed here and
        reported as "no Tickertape data", never raised, so it can't block
        persisting the brokerage_calls-derived fields that ARE reliable."""
        with conn.cursor() as cur:
            cur.execute("SELECT name, symbol FROM instruments WHERE instrument_id = %s", (instrument_id,))
            row = cur.fetchone()
        if not row or not row[0] or not row[1]:
            return None

        name, symbol = row
        slug = guess_slug(symbol, name)
        try:
            return fetch_analyst_consensus(slug)
        except TickertapeFetchError as exc:
            logger.info(
                "consensus_ratings: Tickertape lookup failed for instrument_id=%s (guessed slug=%r): %s",
                instrument_id, slug, exc,
            )
            return None

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        with get_conn() as conn:
            return bulk_upsert_consensus_ratings(conn, rows)
