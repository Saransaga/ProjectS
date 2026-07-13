import logging
from datetime import date

from .. import rss_client
from ..db import get_conn
from ..news.pipeline import enrich
from ..news.ticker_matching import build_alias_index
from ..upsert_news import persist_news_items
from .base import BaseJob

logger = logging.getLogger(__name__)


class RssNewsJob(BaseJob):
    """Polls the fixed set of Indian financial-news RSS feeds in rss_client.py
    (per-feed reliability notes, incl. Business Standard's unverified status,
    live there), runs every entry through the shared news.pipeline enrichment
    (ticker tagging + sentiment + urgency/relevance), and upserts into
    news_items. News doesn't stop on weekends/holidays, so always_force=True
    below bypasses BaseJob's is_trading_day gate."""

    job_name = "rss_news"
    always_force = True

    def fetch(self, run_date: date) -> list[dict]:
        # Built once per run and reused across every article below — each
        # call compiles ~2400 instruments' worth of regexes, too expensive
        # to redo per-article.
        with get_conn() as conn:
            alias_index = build_alias_index(conn)

        feeds = rss_client.fetch_all_feeds()

        rows = []
        for source_type, articles in feeds.items():
            if not articles:
                logger.info("%s: 0 entries", source_type)
                continue
            for article in articles:
                enriched = enrich(article["headline"], article["summary"], source_type, alias_index)
                rows.append(
                    {
                        "source_type": source_type,
                        "external_id": article["external_id"],
                        "headline": article["headline"],
                        "summary": article["summary"],
                        "url": article["url"],
                        "published_at": article["published_at"],
                        **enriched,
                    }
                )
        return rows

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        # persist_news_items takes one source_type per call, so group by that
        # first — it handles the within-batch external_id dedup itself.
        by_source: dict[str, list[dict]] = {}
        for r in rows:
            by_source.setdefault(r["source_type"], []).append(r)

        with get_conn() as conn:
            return sum(persist_news_items(conn, source_type, batch) for source_type, batch in by_source.items())
