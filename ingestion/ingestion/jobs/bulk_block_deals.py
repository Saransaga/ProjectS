import logging
from datetime import date

from .. import nse_client
from ..db import get_conn
from ..fundamentals.util import lookup_instrument_id
from ..upsert_momentum import bulk_upsert_bulk_block_deals
from .base import BaseJob

logger = logging.getLogger(__name__)


class BulkBlockDealsJob(BaseJob):
    """NSE's bulk.csv/block.csv only ever serve "today's" deals (no
    date-range param), so like NseAnnouncementsJob this always asks for
    "what's current right now" rather than backfilling run_date's historical
    deals. always_force=True for the same reason NseAnnouncementsJob needs
    it: the domain spec wants this polled in 2 intraday windows, and without
    always_force, BaseJob's "already succeeded today" dedup would SKIP every
    poll after the first each day. A re-poll re-upserts deals already seen
    (ON CONFLICT DO NOTHING on the full natural key — see upsert_momentum.py)
    rather than duplicating them.

    BSE bulk/block deals are out of scope this phase — every guessed
    api.bseindia.com endpoint returned an ASP.NET error page, not JSON, from
    this environment (see init.sql's Domain 6 section header)."""

    job_name = "bulk_block_deals"
    always_force = True

    def fetch(self, run_date: date) -> list[dict]:
        rows: list[dict] = []
        with get_conn() as conn:
            for deal_type, raw_rows in (("BULK", nse_client.fetch_bulk_deals()), ("BLOCK", nse_client.fetch_block_deals())):
                for r in raw_rows:
                    instrument_id = lookup_instrument_id(conn, r["symbol"])
                    if instrument_id is None:
                        continue  # not an equity we track (e.g. SME-segment listing)
                    rows.append(
                        {
                            "instrument_id": instrument_id,
                            "deal_date": r["deal_date"],
                            "deal_type": deal_type,
                            "client_name": r["client_name"],
                            "buy_sell": r["buy_sell"],
                            "quantity": r["quantity"],
                            "trade_price": r["trade_price"],
                            "source": "NSE",
                        }
                    )
        return rows

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        with get_conn() as conn:
            return bulk_upsert_bulk_block_deals(conn, rows)
