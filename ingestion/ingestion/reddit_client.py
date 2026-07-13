"""Thin wrapper around PRAW (Reddit's official API client) for read-only
polling of a fixed list of subreddits. A registered "script" app's
client_id/client_secret plus read_only mode is enough to list public posts
-- no user login/OAuth flow needed.
"""

import logging
from datetime import datetime, timezone

import praw
import praw.exceptions
import prawcore.exceptions

from .config import config

logger = logging.getLogger(__name__)

SUBREDDITS = ["IndiaInvestments", "stocks"]

# post.selftext can be huge (long-form DD posts) or empty (link posts) --
# cap it so we're not stuffing megabytes into the summary column.
_SUMMARY_MAX_LEN = 1000


def _build_reddit() -> praw.Reddit:
    reddit = praw.Reddit(
        client_id=config.REDDIT_CLIENT_ID,
        client_secret=config.REDDIT_CLIENT_SECRET,
        user_agent=config.REDDIT_USER_AGENT,
    )
    reddit.read_only = True
    return reddit


def fetch_recent_posts(subreddit_names: list[str], limit: int = 50) -> list[dict]:
    """Fetch the `limit` newest posts from each subreddit in
    subreddit_names, normalized to the news_items row shape (external_id,
    headline, summary, url, published_at).

    One bad subreddit (auth failure, rate limit, not found/banned/private)
    is logged and skipped rather than aborting the whole fetch -- callers
    still get results from the subreddits that did work.
    """
    reddit = _build_reddit()
    posts: list[dict] = []

    for name in subreddit_names:
        try:
            subreddit = reddit.subreddit(name)
            for post in subreddit.new(limit=limit):
                posts.append(
                    {
                        "external_id": post.id,
                        "headline": post.title,
                        "summary": (post.selftext or "")[:_SUMMARY_MAX_LEN],
                        "url": f"https://reddit.com{post.permalink}",
                        "published_at": datetime.fromtimestamp(post.created_utc, tz=timezone.utc),
                    }
                )
        except (praw.exceptions.PRAWException, prawcore.exceptions.PrawcoreException) as exc:
            logger.warning("r/%s: fetch failed (%s), skipping", name, exc)
            continue

    return posts
