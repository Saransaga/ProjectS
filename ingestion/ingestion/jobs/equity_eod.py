from datetime import date

from .. import nse_client
from .base import BaseJob


class EquityEodJob(BaseJob):
    job_name = "nse_equity_eod"

    def fetch(self, run_date: date) -> list[dict]:
        rows = nse_client.fetch_equity_bhavcopy(run_date)
        for r in rows:
            r["exchange"] = "NSE"
            r["instrument_type"] = "EQUITY"
            r["series"] = "EQ"
            r["source"] = "NSE_BHAVCOPY"
        return rows
