"""Resolves free-text Telegram input (a raw symbol, or a fragment of a
company name) to a single instrument. Reuses news/ticker_matching's
normalize_name for the same suffix-stripping/punctuation-folding
normalization Domain 4 already established, but does its own bidirectional
containment check instead of calling match_tickers: match_tickers is a
substring search built for tagging a full news article, so it only works
when the alias is shorter than or equal to the input text — backwards for a
short chat query like "reliance" that's *shorter* than the alias "reliance
industries".
"""

from ..news.ticker_matching import normalize_name
from .alias_cache import get_alias_cache

_MIN_QUERY_LENGTH = 3


class AmbiguousQueryError(Exception):
    """Raised when a name-fragment query matches more than one instrument
    equally well — callers (telegram_bot/commands.py) should list the
    candidates rather than silently guessing one."""

    def __init__(self, query: str, candidates: list[dict]):
        self.query = query
        self.candidates = candidates
        super().__init__(f"{len(candidates)} instruments match {query!r}")


def resolve(conn, query: str) -> dict | None:
    """Returns {"instrument_id", "symbol", "name"} for a single unambiguous
    match, or None for no match at all."""
    query = query.strip()
    if not query:
        return None

    cache = get_alias_cache(conn)

    exact = cache.by_symbol.get(query.upper())
    if exact:
        return exact

    normalized_query = normalize_name(query).lower()
    if len(normalized_query) < _MIN_QUERY_LENGTH:
        return None

    matches = {}
    for normalized_name, entry in cache.by_normalized_name.items():
        if normalized_query in normalized_name or normalized_name in normalized_query:
            matches[entry["instrument_id"]] = entry

    if not matches:
        return None
    if len(matches) == 1:
        return next(iter(matches.values()))
    raise AmbiguousQueryError(query, list(matches.values()))
