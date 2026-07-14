from datetime import date

from .. import niftyindices_client
from ..db import get_conn
from ..upsert_events import bulk_upsert_index_rebalancing_schedule
from .base import BaseJob


class IndexRebalancingScheduleJob(BaseJob):
    """Refresh of NSE Indices' published rebalancing cadence per index (see
    niftyindices_client.py) — a slowly-changing reference table, not a time
    series. always_force=True: there's no "already ingested today" concept
    to skip, just "is this still current". Actual inclusion/exclusion events
    (which stocks get added/removed each cycle) are deferred — see
    init.sql's Domain 7 section header for why no free, scrapeable source
    exists for that."""

    job_name = "index_rebalancing_schedule"
    always_force = True

    def fetch(self, run_date: date) -> list[dict]:
        return [{**r, "source": "NSE_INDICES"} for r in niftyindices_client.fetch_rebalancing_schedule()]

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        with get_conn() as conn:
            return bulk_upsert_index_rebalancing_schedule(conn, rows)
