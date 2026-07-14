from datetime import date

from .. import nse_client
from ..db import get_conn
from ..fundamentals.util import lookup_instrument_id
from ..upsert_fno import bulk_upsert_fno_bhavcopy
from .base import BaseJob


class FnoBhavcopyJob(BaseJob):
    """NSE's daily F&O bhavcopy (~36,000 contract rows/day across index and
    stock futures/options) — see nse_client.fetch_fno_bhavcopy and
    init.sql's fno_bhavcopy_daily comment for the instrument_id-resolution
    caveat (only resolved for stock underlyings, always NULL for index
    underlyings like NIFTY/BANKNIFTY). Raises NseNoDataError on holidays,
    same convention as EquityEodJob."""

    job_name = "fno_bhavcopy"

    def fetch(self, run_date: date) -> list[dict]:
        raw_rows = nse_client.fetch_fno_bhavcopy(run_date)

        rows = []
        with get_conn() as conn:
            instrument_cache: dict[str, int | None] = {}
            for r in raw_rows:
                symbol = r["underlying_symbol"]
                if r["underlying_type"] == "STOCK":
                    if symbol not in instrument_cache:
                        instrument_cache[symbol] = lookup_instrument_id(conn, symbol)
                    instrument_id = instrument_cache[symbol]
                else:
                    instrument_id = None  # index underlying, see module docstring

                rows.append({**r, "trade_date": run_date, "instrument_id": instrument_id, "source": "NSE_BHAVCOPY"})
        return rows

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        with get_conn() as conn:
            return bulk_upsert_fno_bhavcopy(conn, rows)
