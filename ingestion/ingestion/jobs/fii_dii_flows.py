import logging
from datetime import date

from .. import nse_client, nse_corporate_client
from ..db import get_conn
from ..fundamentals.util import parse_nse_date
from ..upsert_momentum import bulk_upsert_fii_dii_cash_flows, bulk_upsert_fno_participant_oi
from .base import BaseJob

logger = logging.getLogger(__name__)

_CASH_CATEGORY_MAP = {"FII/FPI": "FII", "DII": "DII"}


class FiiDiiFlowsJob(BaseJob):
    """Two NSE sources bundled under one Domain 6 "FII/DII activity" job:

    - Cash-market net buy/sell (fii_dii_cash_flows): NSE's fiidiiTradeReact
      endpoint always returns "whatever was last published" — it has no
      from_date/to_date parameter — so like CorporateActionsJob, backfilling
      a past run_date re-fetches today's figures, it doesn't reconstruct
      that date's historical view. The record's own embedded `date` field
      (parsed here) is what actually gets stored as flow_date, which is why
      this can still land correctly keyed even though the fetch itself
      isn't date-parameterized.
    - F&O participant-wise open interest (fno_participant_oi): unlike the
      above, this NSE archive genuinely is dated by run_date (a real
      historical snapshot), so backfilling old dates works correctly for
      this half of the job. See init.sql's fno_participant_oi comment for
      why this stands in for "F&O segment FII/DII activity" rather than a
      turnover value.

    A missing participant-OI file for run_date (holiday) raises
    NseNoDataError, which SKIPs the whole job per BaseJob's default handling
    — same as EquityEodJob's holiday behavior.
    """

    job_name = "fii_dii_flows"

    def fetch(self, run_date: date) -> dict:
        cash_rows = []
        for r in nse_corporate_client.fetch_fii_dii_activity():
            category = _CASH_CATEGORY_MAP.get(r.get("category"))
            flow_date = parse_nse_date(r.get("date"))
            if category is None or flow_date is None:
                logger.warning("fii/dii cash-flow record missing a known category/date, skipping: %r", r)
                continue
            cash_rows.append(
                {
                    "flow_date": flow_date,
                    "category": category,
                    "buy_value_cr": r.get("buyValue"),
                    "sell_value_cr": r.get("sellValue"),
                    "net_value_cr": r.get("netValue"),
                    "source": "NSE",
                }
            )

        oi_rows = [{"oi_date": run_date, "source": "NSE", **r} for r in nse_client.fetch_participant_oi(run_date)]

        return {"cash": cash_rows, "participant_oi": oi_rows}

    def _persist(self, run_date: date, rows: dict) -> int:
        with get_conn() as conn:
            cash_count = bulk_upsert_fii_dii_cash_flows(conn, rows["cash"])
            oi_count = bulk_upsert_fno_participant_oi(conn, rows["participant_oi"])
        return cash_count + oi_count
