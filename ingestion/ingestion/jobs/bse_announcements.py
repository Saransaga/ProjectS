import logging
from datetime import date, datetime

from .. import bse_client
from ..db import get_conn
from ..news.pipeline import enrich
from ..news.ticker_matching import build_alias_index
from ..upsert_news import persist_news_items
from .base import BaseJob

logger = logging.getLogger(__name__)

# Confirmed against a real response while wiring this up: ATTACHMENTNAME is
# just a filename (e.g. "69c834c6-...pdf"), served from this fixed base path.
# Verified live: a HEAD request against a real ATTACHMENTNAME under this base
# returned 200 application/pdf. Same "verify before fully trusting" spirit as
# the rest of this file — BSE could change this path without notice.
_ATTACHMENT_BASE_URL = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"


def _parse_bse_datetime(value: str | None) -> datetime | None:
    """BSE's NEWS_DT/DT_TM are ISO 8601-ish, e.g. "2026-07-13T14:15:50.937"
    (confirmed against a real response) — no timezone suffix, same
    naive-datetime handling as fundamentals.util.parse_nse_datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class BseAnnouncementsJob(BaseJob):
    """BSE counterpart to NseAnnouncementsJob. BSE's announcements endpoint is
    flaky from this environment — an empty `{}` body one moment, 50 real
    announcement records the next (see bse_client.fetch_announcements'
    docstring) — wired in anyway per this codebase's established pattern of
    documenting unverified/unreliable endpoints rather than skipping them (see
    bse_client.py's Sensex fetch + jobs/index_eod.py's handling of it). A
    BseFetchError here degrades to zero rows and a logged warning rather than
    failing the job, exactly like index_eod.py already does for the Sensex
    close — so this job is expected to legitimately swing between SUCCESS
    with real rows and SUCCESS with zero rows run to run.

    Field names used below (NEWSID, HEADLINE, MORE, NEWS_DT, ATTACHMENTNAME,
    SCRIP_CD, SLONGNAME, NSURL) are confirmed against a real BSE response
    captured while building this, not guessed. always_force=True is required,
    same reasoning as NseAnnouncementsJob: without it, BaseJob's
    "already succeeded today" dedup would make every 5-minute poll after the
    first one each day a no-op."""

    job_name = "bse_announcements"
    always_force = True

    def fetch(self, run_date: date) -> list[dict]:
        try:
            raw_rows = bse_client.fetch_announcements(run_date, run_date)
        except bse_client.BseNoDataError:
            raw_rows = []
        except bse_client.BseFetchError:
            logger.warning(
                "BSE announcements fetch failed for %s, continuing with no rows "
                "— see bse_client.py module docstring",
                run_date,
                exc_info=True,
            )
            raw_rows = []

        rows: list[dict] = []
        with get_conn() as conn:
            alias_index = build_alias_index(conn)
            for r in raw_rows:
                external_id = r.get("NEWSID")
                if not external_id:
                    continue
                external_id = str(external_id)

                # HEADLINE is sometimes truncated with "..." for long board-meeting
                # style announcements, with the full text in MORE (often "" for
                # short/routine ones, where HEADLINE alone is already complete) —
                # mirrors NSE's desc/attchmntText short-category/full-text split.
                headline = r.get("HEADLINE") or r.get("NEWSSUB") or r.get("CATEGORYNAME") or ""
                summary = r.get("MORE") or None

                # Unlike NSE's feed, BSE doesn't hand back an NSE-style ticker —
                # only a numeric SCRIP_CD and the company's long name (SLONGNAME).
                # lookup_instrument_id() only matches exchange='NSE' symbols, so a
                # scrip code can't resolve there; rely on enrich()'s text-based
                # alias matching against SLONGNAME (folded into the enrich() input
                # text below) as the ticker-tagging path for BSE announcements.
                text_for_matching = f"{headline}. {summary or ''} {r.get('SLONGNAME') or ''}"

                enrichment = enrich(text_for_matching, None, "BSE_ANNOUNCEMENT", alias_index)
                ticker_ids = set(enrichment["ticker_ids"])

                attachment_name = r.get("ATTACHMENTNAME")
                url = f"{_ATTACHMENT_BASE_URL}{attachment_name}" if attachment_name else r.get("NSURL")

                rows.append(
                    {
                        "external_id": external_id,
                        "headline": headline,
                        "summary": summary,
                        "url": url,
                        "published_at": _parse_bse_datetime(r.get("NEWS_DT") or r.get("DT_TM")),
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
            return persist_news_items(conn, "BSE_ANNOUNCEMENT", rows)
