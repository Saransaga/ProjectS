import logging
from datetime import date

from .. import nse_corporate_client
from ..db import get_conn
from ..fundamentals.util import lookup_instrument_id, parse_nse_datetime
from ..news.pipeline import enrich
from ..news.ticker_matching import build_alias_index
from ..upsert_news import persist_news_items
from .base import BaseJob

logger = logging.getLogger(__name__)


class NseAnnouncementsJob(BaseJob):
    """Polls NSE's real-time corporate-announcements feed. Meant to run every
    few minutes during market hours, so fetch() only asks NSE for run_date's
    own window ("what's new right now"), not a history backfill — a re-poll
    just re-upserts anything already seen (persist_news_items is keyed on
    NSE's own seq_id, so that's a no-op, not a duplicate). always_force=True
    is required here, not just nice-to-have: without it, BaseJob's
    "already succeeded today" dedup would make every poll after the first
    one each day a no-op SKIP, defeating the every-few-minutes schedule.

    Unlike RSS/Reddit sources, an announcement carries NSE's own `symbol`
    field — an exact, authoritative ticker, not something to infer from free
    text. So each row's final ticker_ids is the union of that direct lookup
    and whatever enrich()'s text-based alias matching finds (the announcement
    text can also name other companies, e.g. an M&A announcement)."""

    job_name = "nse_announcements"
    always_force = True

    def fetch(self, run_date: date) -> list[dict]:
        raw_rows = nse_corporate_client.fetch_corporate_announcements(
            from_date=run_date, to_date=run_date
        )

        rows: list[dict] = []
        with get_conn() as conn:
            alias_index = build_alias_index(conn)
            for r in raw_rows:
                external_id = r.get("seq_id")
                if not external_id:
                    continue  # no stable dedup key to upsert on, skip rather than risk a blank/NULL key collision
                external_id = str(external_id)

                headline = r.get("desc") or ""
                summary = r.get("attchmntText")
                symbol = r.get("symbol")

                enrichment = enrich(headline, summary, "NSE_ANNOUNCEMENT", alias_index)
                ticker_ids = set(enrichment["ticker_ids"])
                direct_instrument_id = lookup_instrument_id(conn, symbol) if symbol else None
                if direct_instrument_id is not None:
                    # The announcement's own symbol is strictly more reliable than
                    # text-based matching for the announcement's own company —
                    # union rather than replace, since the text can also name others.
                    ticker_ids.add(direct_instrument_id)

                rows.append(
                    {
                        "external_id": external_id,
                        "headline": headline,
                        "summary": summary,
                        "url": r.get("attchmntFile"),
                        "published_at": parse_nse_datetime(r.get("an_dt")),
                        "sentiment_label": enrichment["sentiment_label"],
                        "sentiment_score": enrichment["sentiment_score"],
                        "urgency": enrichment["urgency"],
                        "relevance_score": enrichment["relevance_score"],
                        "source_credibility_weight": enrichment["source_credibility_weight"],
                        "ticker_ids": ticker_ids,
                    }
                )
        return rows

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        with get_conn() as conn:
            return persist_news_items(conn, "NSE_ANNOUNCEMENT", rows)
