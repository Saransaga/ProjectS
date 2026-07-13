import logging
import time
from datetime import date, timedelta

from .. import nse_corporate_client
from ..db import get_conn
from ..fundamentals.util import lookup_instrument_id, parse_nse_date, parse_nse_datetime
from ..fundamentals.xbrl_financial import parse_financial_results
from ..upsert_fundamentals import bulk_upsert_fundamentals_quarterly
from .base import BaseJob

logger = logging.getLogger(__name__)

# How far back to look for "financial results" board-meeting intimations —
# wide enough to catch late filers relative to their announced meeting date,
# narrow enough to keep the per-symbol XBRL fetch count small.
_BOARD_MEETING_LOOKBACK_DAYS = 10
_INTER_SYMBOL_DELAY_SECONDS = 0.3


class FinancialResultsJob(BaseJob):
    """The spec's "within 24h of filing, webhook/poll" requirement, implemented
    as: bulk-poll board meetings for "Financial Results" purpose (cheap, one
    call, all symbols), then only call the per-symbol financial-results/XBRL
    endpoints for that day's actual reporters — not all ~2,400 equities."""

    job_name = "financial_results"

    def fetch(self, run_date: date) -> list[dict]:
        meetings = nse_corporate_client.fetch_board_meetings(
            run_date - timedelta(days=_BOARD_MEETING_LOOKBACK_DAYS), run_date
        )
        candidate_symbols = sorted(
            {
                m["bm_symbol"]
                for m in meetings
                if m.get("bm_symbol")
                and "financial result" in f"{m.get('bm_purpose', '')} {m.get('bm_desc', '')}".lower()
            }
        )

        results = []
        with get_conn() as conn:
            for symbol in candidate_symbols:
                instrument_id = lookup_instrument_id(conn, symbol)
                if instrument_id is None:
                    continue

                existing = self._existing_periods(conn, instrument_id)
                try:
                    filings = nse_corporate_client.fetch_financial_results(
                        symbol,
                        from_date=run_date - timedelta(days=_BOARD_MEETING_LOOKBACK_DAYS),
                        to_date=run_date,
                    )
                except Exception:
                    logger.warning("financial-results fetch failed for %s", symbol, exc_info=True)
                    continue

                for f in filings:
                    row = self._parse_filing(instrument_id, f, existing)
                    if row is not None:
                        # Guard against NSE listing the same period twice in one
                        # poll (e.g. an amended filing) — a single upsert batch
                        # can't touch the same (instrument_id, period_end_date,
                        # consolidated) conflict target more than once.
                        key = (row["period_end_date"], row["consolidated"])
                        existing.add(key)
                        results.append(row)

                time.sleep(_INTER_SYMBOL_DELAY_SECONDS)
        return results

    def _parse_filing(self, instrument_id: int, f: dict, existing: set) -> dict | None:
        period_end = parse_nse_date(f.get("toDate"))
        from_date = parse_nse_date(f.get("fromDate"))
        consolidated = (f.get("consolidated") or "").strip().lower() == "consolidated"
        xbrl_url = f.get("xbrl")

        if period_end is None or from_date is None or not xbrl_url or xbrl_url == "-":
            return None
        if (period_end, consolidated) in existing:
            return None  # already ingested, skip the XBRL download

        try:
            xbrl_bytes = nse_corporate_client.fetch_xbrl(xbrl_url)
            parsed = parse_financial_results(xbrl_bytes, from_date, period_end)
        except Exception:
            logger.warning("XBRL parse failed for instrument_id=%s period=%s", instrument_id, period_end, exc_info=True)
            return None
        if parsed is None:
            return None

        return {
            "instrument_id": instrument_id,
            "period_end_date": period_end,
            "financial_year": f.get("financialYear"),
            "reporting_quarter": f.get("relatingTo"),
            "consolidated": consolidated,
            "broadcast_date": parse_nse_datetime(f.get("broadCastDate")),
            "xbrl_url": xbrl_url,
            "source": "NSE",
            **parsed,
        }

    def _existing_periods(self, conn, instrument_id: int) -> set:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT period_end_date, consolidated FROM fundamentals_quarterly WHERE instrument_id = %s",
                (instrument_id,),
            )
            return {(row[0], row[1]) for row in cur.fetchall()}

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        with get_conn() as conn:
            return bulk_upsert_fundamentals_quarterly(conn, rows)
