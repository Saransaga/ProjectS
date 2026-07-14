import re
from datetime import date

from .. import nse_corporate_client
from ..db import get_conn
from ..fundamentals.util import lookup_instrument_id, parse_nse_date
from ..upsert_events import bulk_upsert_ipo_listings
from .base import BaseJob

_PRICE_RE = re.compile(r"(\d+(?:\.\d+)?)")


def _parse_price_band(text: str | None) -> tuple[float | None, float | None]:
    if not text:
        return None, None
    numbers = _PRICE_RE.findall(text)
    if not numbers:
        return None, None
    if len(numbers) == 1:
        return float(numbers[0]), float(numbers[0])
    return float(numbers[0]), float(numbers[1])


class IpoListingsJob(BaseJob):
    """NSE's mainboard IPO calendar (all-upcoming-issues?category=ipo) only
    ever lists issues currently bidding or recently closed — once a stock
    actually lists, it drops off that feed entirely (it's an "upcoming
    issues" list, not a historical archive). So this job does two
    independent things each run:

    1. Upsert whatever's currently on the live feed (status ACTIVE/CLOSED).
    2. For rows already in ipo_listings still missing instrument_id, check
       if Domain 1's equity job has picked the symbol up yet and, if so,
       backfill listing_date/listing_* from the first ohlcv_daily row on/
       after issue_end_date — the "first-day data" the spec asks for,
       derived rather than fetched from a nonexistent NSE "IPO listing-day
       performance" endpoint, same spirit as ohlcv_weekly's continuous
       aggregate.

    always_force=True: like CorporateCalendarJob, NSE's feed always serves
    "whatever's current right now", and the backfill check needs to run
    every day regardless of whether today already "succeeded"."""

    job_name = "ipo_listings"
    always_force = True

    def fetch(self, run_date: date) -> list[dict]:
        rows: list[dict] = []
        with get_conn() as conn:
            for r in nse_corporate_client.fetch_ipo_listings():
                symbol = r.get("symbol")
                issue_start = parse_nse_date(r.get("issueStartDate"))
                if not symbol or issue_start is None:
                    continue
                price_low, price_high = _parse_price_band(r.get("issuePrice"))
                issue_size = r.get("issueSize")
                rows.append(
                    {
                        "symbol": symbol,
                        "issue_start_date": issue_start,
                        "company_name": r.get("companyName") or symbol,
                        "instrument_id": lookup_instrument_id(conn, symbol),
                        "issue_price_low": price_low,
                        "issue_price_high": price_high,
                        "issue_size_shares": int(issue_size) if issue_size else None,
                        "issue_end_date": parse_nse_date(r.get("issueEndDate")),
                        "status": (r.get("status") or "ACTIVE").upper(),
                        "listing_date": None,
                        "listing_open": None,
                        "listing_high": None,
                        "listing_low": None,
                        "listing_close": None,
                        "listing_volume": None,
                        "source": "NSE",
                    }
                )

            rows.extend(self._backfill_listed(conn))
        return rows

    def _backfill_listed(self, conn) -> list[dict]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT symbol, company_name, issue_price_low, issue_price_high,
                       issue_size_shares, issue_start_date, issue_end_date, source
                FROM ipo_listings
                WHERE instrument_id IS NULL AND status != 'LISTED' AND issue_end_date IS NOT NULL
                """
            )
            pending = cur.fetchall()

        backfilled = []
        for symbol, company_name, price_low, price_high, issue_size, issue_start, issue_end, source in pending:
            instrument_id = lookup_instrument_id(conn, symbol)
            if instrument_id is None:
                continue
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT trade_date, open, high, low, close, volume
                    FROM ohlcv_daily
                    WHERE instrument_id = %s AND trade_date >= %s
                    ORDER BY trade_date ASC
                    LIMIT 1
                    """,
                    (instrument_id, issue_end),
                )
                first_day = cur.fetchone()
            if first_day is None:
                continue
            trade_date, o, h, l, c, v = first_day
            backfilled.append(
                {
                    "symbol": symbol,
                    "issue_start_date": issue_start,
                    "company_name": company_name,
                    "instrument_id": instrument_id,
                    "issue_price_low": price_low,
                    "issue_price_high": price_high,
                    "issue_size_shares": issue_size,
                    "issue_end_date": issue_end,
                    "status": "LISTED",
                    "listing_date": trade_date,
                    "listing_open": o,
                    "listing_high": h,
                    "listing_low": l,
                    "listing_close": c,
                    "listing_volume": v,
                    "source": source,
                }
            )
        return backfilled

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        with get_conn() as conn:
            return bulk_upsert_ipo_listings(conn, rows)
