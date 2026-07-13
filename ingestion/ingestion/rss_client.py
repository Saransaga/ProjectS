"""Indian financial-news RSS feeds, fetched with a browser User-Agent and
parsed with feedparser into a common article shape (external_id/headline/
summary/url/published_at).

Six feeds are configured, each mapping 1:1 to a news_items.source_type:
ET Markets, Moneycontrol Business, Moneycontrol Markets, Mint, Google News
(NSE-scoped search), and Business Standard.

UNVERIFIED FEED: Business Standard's markets-106.rss returned HTTP 403 from
this environment (Akamai/WAF block) even with a browser User-Agent — same
"blocked from some hosts, may work elsewhere" situation as bse_client.py's
unverified index-history endpoint. It's still wired in below; if it starts
working from a different environment, no code change is needed. Every other
feed here was confirmed live (HTTP 200, real <item> entries) during
implementation.

Fetching is per-feed and isolated: fetch_all_feeds() catches and logs any
single feed's failure (network error, block, malformed XML) rather than
propagating it, so one bad feed never takes down the whole job.
"""

import logging
from datetime import datetime, timezone

import feedparser
import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import config

logger = logging.getLogger(__name__)

FEEDS = {
    "RSS_ET_MARKETS": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "RSS_MONEYCONTROL_BUSINESS": "https://www.moneycontrol.com/rss/business.xml",
    "RSS_MONEYCONTROL_MARKETS": "https://www.moneycontrol.com/rss/marketreports.xml",
    "RSS_MINT": "https://www.livemint.com/rss/markets",
    "RSS_GOOGLE_NEWS": "https://news.google.com/rss/search?q=NSE+India+stocks&hl=en-IN&gl=IN&ceid=IN:en",
    "RSS_BUSINESS_STANDARD": "https://www.business-standard.com/rss/markets-106.rss",  # see module docstring, unverified from this host
}

_HEADERS = {
    "User-Agent": config.HTTP_USER_AGENT,
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


class RssFetchError(Exception):
    """Non-2xx response, or a feed body feedparser couldn't extract any entries from."""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((RssFetchError, requests.RequestException)),
    reraise=True,
)
def _fetch_raw(url: str) -> bytes:
    resp = requests.get(url, headers=_HEADERS, timeout=20)
    if resp.status_code != 200:
        raise RssFetchError(f"unexpected response ({resp.status_code}) from {url}")
    return resp.content


def _parse_published(entry) -> datetime | None:
    struct = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not struct:
        return None
    try:
        return datetime(*struct[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def parse_entries(url: str) -> list[dict]:
    """Fetch + parse one feed into raw article dicts. Raises RssFetchError /
    requests.RequestException on transport failure — callers should catch
    per-feed (fetch_all_feeds does this) so one broken feed doesn't take
    down the whole job."""
    raw = _fetch_raw(url)
    parsed = feedparser.parse(raw)
    if parsed.bozo and not parsed.entries:
        raise RssFetchError(f"unparseable feed ({parsed.get('bozo_exception')}) from {url}")

    articles = []
    for entry in parsed.entries:
        headline = getattr(entry, "title", None)
        if not headline:
            continue  # can't run enrichment / dedup without a headline
        external_id = (
            getattr(entry, "id", None) or getattr(entry, "guid", None) or getattr(entry, "link", None)
        )
        if not external_id:
            continue  # no stable dedup key available for this entry
        articles.append(
            {
                "external_id": external_id,
                "headline": headline,
                "summary": getattr(entry, "summary", None) or getattr(entry, "description", None),
                "url": getattr(entry, "link", None),
                "published_at": _parse_published(entry),
            }
        )
    return articles


def fetch_all_feeds() -> dict[str, list[dict]]:
    """Fetch+parse every configured feed, keyed by source_type. A feed that
    fails entirely (blocked, timed out, malformed) comes back as an empty
    list with a logged warning rather than raising."""
    results: dict[str, list[dict]] = {}
    for source_type, url in FEEDS.items():
        try:
            articles = parse_entries(url)
        except Exception:
            logger.warning("%s: failed to fetch/parse %s", source_type, url, exc_info=True)
            articles = []
        results[source_type] = articles
    return results
