from datetime import date

from .. import nse_client
from ..db import get_conn
from ..fundamentals.util import lookup_instrument_id
from ..upsert_momentum import update_delivery_volume
from .base import BaseJob


class DeliverableVolumeJob(BaseJob):
    """Backfills ohlcv_daily.delivery_qty/delivery_pct — present in the
    schema since Domain 1 but always NULL until now (see upsert.py's
    bulk_upsert_ohlcv docstring) — from NSE's older "full bhavcopy" archive,
    the only free source that carries delivery data at all (the UDiFF
    bhavcopy EquityEodJob uses doesn't have it). This is an UPDATE, not an
    INSERT: it runs after EquityEodJob has already created the day's
    ohlcv_daily rows and only enriches them; a symbol with no matching
    ohlcv_daily row for run_date is a no-op update, not an error. Raises
    NseNoDataError on holidays, same convention as EquityEodJob."""

    job_name = "deliverable_volume"

    def fetch(self, run_date: date) -> list[dict]:
        raw_rows = nse_client.fetch_delivery_bhavcopy(run_date)

        rows = []
        with get_conn() as conn:
            for r in raw_rows:
                instrument_id = lookup_instrument_id(conn, r["symbol"])
                if instrument_id is None:
                    continue
                rows.append(
                    {
                        "instrument_id": instrument_id,
                        "trade_date": run_date,
                        "delivery_qty": r["delivery_qty"],
                        "delivery_pct": r["delivery_pct"],
                    }
                )
        return rows

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        with get_conn() as conn:
            return update_delivery_volume(conn, rows)
