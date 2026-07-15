"""Read-only polling of a fixed list of subreddits via Reddit's public
`.json` listing endpoints (e.g. https://www.reddit.com/r/stocks/new.json) --
no API credentials required, just a browser User-Agent, same approach as
rss_client.py.

Registering a "script" app at reddit.com/prefs/apps (the old PRAW-based
route this module used to use) is no longer reliably self-serve, so this
scrapes the same public listings a logged-out browser sees instead.

UNVERIFIED FROM THIS ENVIRONMENT: every subreddit tried here returned HTTP
403 with an Akamai/PerimeterX "Blocked" bot-detection page from this sandbox,
even with a full browser User-Agent -- the same "blocked from some hosts,
may work elsewhere" situation as bse_client.py's index-history endpoint and
rss_client.py's Business Standard feed. Before relying on this in
production: confirm a plain `curl -A "<browser UA>"
https://www.reddit.com/r/stocks/new.json` succeeds from the actual
deployment host. If Reddit blocks datacenter IPs generally, no User-Agent
tweak here will fix it -- an IP-based block requires routing through a
residential/datacenter-friendly proxy, or falling back to a paid data
provider.

Fetching is per-subreddit and isolated: fetch_recent_posts() catches and
logs any single subreddit's failure (block, rate limit, not found/banned/
private, malformed JSON) rather than aborting the whole fetch -- callers
still get results from the subreddits that did work.
"""

import logging
from datetime import datetime, timezone

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import config

logger = logging.getLogger(__name__)

SUBREDDITS = ["IndiaInvestments", "stocks"]

# post.selftext can be huge (long-form DD posts) or empty (link posts) --
# cap it so we're not stuffing megabytes into the summary column.
_SUMMARY_MAX_LEN = 1000

_HEADERS = {
    "User-Agent": config.HTTP_USER_AGENT,
    "Accept": "application/json",
}


class RedditFetchError(Exception):
    """Non-2xx response, or a listing body with no parseable `data.children`."""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((RedditFetchError, requests.RequestException)),
    reraise=True,
)
def _fetch_listing(subreddit_name: str, limit: int) -> dict:
    url = f"https://www.reddit.com/r/{subreddit_name}/new.json"
    resp = requests.get(url, headers=_HEADERS, params={"limit": limit, "raw_json": 1}, timeout=20)
    if resp.status_code != 200:
        raise RedditFetchError(f"unexpected response ({resp.status_code}) from {url}")
    try:
        return resp.json()
    except ValueError as exc:
        raise RedditFetchError(f"non-JSON response from {url}") from exc


def fetch_recent_posts(subreddit_names: list[str], limit: int = 50) -> list[dict]:
    """Fetch the `limit` newest posts from each subreddit in
    subreddit_names, normalized to the news_items row shape (external_id,
    headline, summary, url, published_at).
    """
    posts: list[dict] = []

    for name in subreddit_names:
        try:
            listing = _fetch_listing(name, limit)
            children = listing.get("data", {}).get("children", [])
        except (RedditFetchError, requests.RequestException) as exc:
            logger.warning("r/%s: fetch failed (%s), skipping", name, exc)
            continue

        for child in children:
            post = child.get("data", {})
            post_id = post.get("id")
            title = post.get("title")
            if not post_id or not title:
                continue  # no stable dedup key / nothing to score
            posts.append(
                {
                    "external_id": post_id,
                    "headline": title,
                    "summary": (post.get("selftext") or "")[:_SUMMARY_MAX_LEN],
                    "url": f"https://reddit.com{post.get('permalink', '')}",
                    "published_at": datetime.fromtimestamp(
                        post["created_utc"], tz=timezone.utc
                    )
                    if post.get("created_utc")
                    else None,
                }
            )

    return posts
