import logging
from datetime import date

from .. import reddit_client
from ..config import config
from ..db import get_conn
from ..news import pipeline
from ..news.ticker_matching import build_alias_index
from ..upsert_news import persist_news_items
from .base import BaseJob

logger = logging.getLogger(__name__)


class RedditSentimentJob(BaseJob):
    """Polls r/IndiaInvestments and r/stocks for recent posts via PRAW,
    scoring each through the shared news pipeline (ticker tagging +
    sentiment + urgency/relevance). Reddit credentials are optional infra --
    if unset, this job just reports 0 rows instead of failing the whole
    ingestion run. News doesn't stop on weekends/holidays, so
    always_force=True bypasses BaseJob's is_trading_day gate."""

    job_name = "reddit_sentiment"
    always_force = True

    def fetch(self, run_date: date) -> list[dict]:
        if not config.REDDIT_CLIENT_ID or not config.REDDIT_CLIENT_SECRET:
            logger.warning("Reddit credentials not configured, skipping")
            return []

        posts = reddit_client.fetch_recent_posts(reddit_client.SUBREDDITS)

        # Built once per run and reused across every enrich() call below --
        # rebuilding the alias index per-post would be needlessly expensive.
        with get_conn() as conn:
            alias_index = build_alias_index(conn)

        rows = []
        for post in posts:
            enriched = pipeline.enrich(post["headline"], post["summary"], "REDDIT", alias_index)
            rows.append({**post, **enriched})
        return rows

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        with get_conn() as conn:
            return persist_news_items(conn, "REDDIT", rows)
