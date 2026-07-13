import logging
from datetime import date

from .. import nse_corporate_client
from ..db import get_conn
from ..fundamentals.corporate_actions import classify
from ..fundamentals.util import lookup_instrument_id, parse_nse_date
from ..upsert_fundamentals import bulk_upsert_corporate_actions
from .base import BaseJob

logger = logging.getLogger(__name__)


class CorporateActionsJob(BaseJob):
    """Daily poll of NSE's corporate-actions calendar. NSE's endpoint only
    exposes the current near-term list (no true point-in-time history), so
    this always ingests "whatever NSE shows as upcoming/recent right now"
    regardless of run_date — backfilling a past date re-fetches today's list,
    it doesn't reconstruct that date's historical view."""

    job_name = "corporate_actions"

    def fetch(self, run_date: date) -> list[dict]:
        rows = nse_corporate_client.fetch_corporate_actions()

        results = []
        with get_conn() as conn:
            for r in rows:
                symbol, subject = r.get("symbol"), r.get("subject")
                if not symbol or not subject:
                    # A malformed record shouldn't sink every other legitimate
                    # action fetched this run (same "skip the bad one, keep
                    # going" spirit as rss_client.py's per-feed isolation).
                    logger.warning("corporate action record missing symbol/subject, skipping: %r", r)
                    continue
                instrument_id = lookup_instrument_id(conn, symbol)
                if instrument_id is None:
                    continue  # not an equity we track (e.g. govt securities, debt instruments)
                results.append(
                    {
                        "instrument_id": instrument_id,
                        "ex_date": parse_nse_date(r.get("exDate")),
                        "record_date": parse_nse_date(r.get("recDate")),
                        "raw_subject": subject,
                        "series": r.get("series"),
                        "source": "NSE",
                        **classify(subject),
                    }
                )
        return results

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        with get_conn() as conn:
            return bulk_upsert_corporate_actions(conn, rows)
