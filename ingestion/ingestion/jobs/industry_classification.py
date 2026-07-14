import logging
from datetime import date

from .. import niftyindices_client
from ..db import get_conn
from ..upsert import bulk_upsert_sector_classification
from .base import BaseJob

logger = logging.getLogger(__name__)


class IndustryClassificationJob(BaseJob):
    """Populates instruments.sector from NSE's sectoral/thematic index
    constituent CSVs (see niftyindices_client.SECTOR_INDEX_SLUGS) — a
    slowly-changing reference table, same always_force=True cadence class as
    IndexRebalancingScheduleJob, not a time series.

    Coverage is partial by design: only symbols that are members of one of
    the curated sectoral/thematic indices get classified. A large fraction
    of the ~2,400 listed equities aren't in any of them and stay NULL —
    that's the correct "leave NULL, don't guess" outcome, not a bug to chase
    (see this domain's plan doc for why a fuller per-symbol classification
    source — NSE's quote-equity industryInfo — is deliberately not used yet:
    unverified/Akamai-blocked from the environment this was built in).

    instruments.industry is deliberately left untouched here: the CSVs'
    own "Industry" column is actually sector-tier granularity (see
    niftyindices_client.py's module docstring), not the finer-grained
    industry NSE's 4-tier scheme distinguishes — mapping it there too would
    silently duplicate the sector value under a column name that promises
    more precision than this source actually has.
    """

    job_name = "industry_classification"
    always_force = True

    def fetch(self, run_date: date) -> list[dict]:
        rows: dict[str, str] = {}
        for slug in niftyindices_client.SECTOR_INDEX_SLUGS:
            try:
                constituents = niftyindices_client.fetch_sector_constituents(slug)
            except niftyindices_client.NiftyIndicesFetchError as exc:
                # One bad/renamed slug shouldn't take the whole job down —
                # same "log and continue" spirit as rss_news.py's per-feed
                # isolation.
                logger.warning("industry_classification: %s failed: %s", slug, exc)
                continue
            for row in constituents:
                # A symbol can legitimately appear in more than one sectoral/
                # thematic index (e.g. a large bank in both niftybanklist and
                # niftyfinancelist) — its own "Industry" classification is
                # the same value from NSE's perspective either way, so last-
                # write-wins here is a no-op in practice, not a real conflict.
                rows[row["symbol"]] = row["sector"]
        return [{"symbol": symbol, "sector": sector} for symbol, sector in rows.items()]

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        with get_conn() as conn:
            return bulk_upsert_sector_classification(conn, rows)
