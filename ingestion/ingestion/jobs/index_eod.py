import logging
from datetime import date

from .. import bse_client, nse_client
from .base import BaseJob

logger = logging.getLogger(__name__)


class IndexEodJob(BaseJob):
    job_name = "index_eod"

    def fetch(self, run_date: date) -> list[dict]:
        rows = nse_client.fetch_index_close(run_date)
        for r in rows:
            r["exchange"] = "NSE"
            r["instrument_type"] = "INDEX"
            r["source"] = "NSE_INDEX_CLOSE"

        # Sensex/BSE is a best-effort addendum on an unverified endpoint (see
        # bse_client.py) — a BSE failure shouldn't fail the whole job when the
        # reliable NSE indices (Nifty 50, Nifty Bank) succeeded.
        try:
            sensex = bse_client.fetch_sensex_close(run_date)
        except bse_client.BseNoDataError:
            sensex = None
        except bse_client.BseFetchError:
            logger.warning("Sensex fetch failed for %s, continuing without it", run_date, exc_info=True)
            sensex = None

        if sensex:
            sensex["exchange"] = "BSE"
            sensex["instrument_type"] = "INDEX"
            sensex["source"] = "BSE_INDEX_CLOSE"
            rows.append(sensex)

        if not rows:
            raise nse_client.NseNoDataError(f"no index data for {run_date}")
        return rows
