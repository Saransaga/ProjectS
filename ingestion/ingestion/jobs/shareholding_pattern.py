from datetime import date

from .. import nse_corporate_client
from ..db import get_conn
from ..fundamentals.util import lookup_instrument_id, parse_nse_date
from ..upsert_fundamentals import bulk_upsert_shareholding_pattern
from .base import BaseJob


class ShareholdingPatternJob(BaseJob):
    """Weekly poll of NSE's bulk shareholding-pattern filings list. Ships
    Promoter %/Public % directly (no XBRL parsing needed — NSE includes them
    as plain JSON fields on the bulk list). FII %/DII %/Pledged % require
    parsing the dimensional shareholding-pattern XBRL, which is out of scope
    for this pass — see README — so those columns stay NULL for now.

    always_force=True: scheduled for Sunday (see scheduler.py), which
    is_trading_day() always rejects — without this, the weekly cron would
    SKIPPED every single run and this table would never get populated."""

    job_name = "shareholding_pattern"
    always_force = True

    def fetch(self, run_date: date) -> list[dict]:
        rows = nse_corporate_client.fetch_shareholding_master()

        # NSE's list can carry more than one record for the same instrument +
        # period (e.g. a revised/amended filing) — keep only the most recent
        # submission per (instrument_id, period_end_date), otherwise a single
        # upsert batch would try to touch the same conflict target twice.
        by_key: dict[tuple, dict] = {}
        with get_conn() as conn:
            for r in rows:
                instrument_id = lookup_instrument_id(conn, r.get("symbol") or "")
                if instrument_id is None:
                    continue
                period_end = parse_nse_date(r.get("date"))
                if period_end is None:
                    continue
                submission_date = parse_nse_date(r.get("submissionDate"))
                key = (instrument_id, period_end)
                if key in by_key and (by_key[key]["submission_date"] or date.min) >= (submission_date or date.min):
                    continue
                by_key[key] = {
                    "instrument_id": instrument_id,
                    "period_end_date": period_end,
                    "promoter_pct": r.get("pr_and_prgrp"),
                    "public_pct": r.get("public_val"),
                    "fii_pct": None,
                    "dii_pct": None,
                    "pledged_promoter_pct": None,
                    "submission_date": submission_date,
                    "xbrl_url": r.get("xbrl"),
                    "source": "NSE",
                }
        return list(by_key.values())

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        with get_conn() as conn:
            return bulk_upsert_shareholding_pattern(conn, rows)
