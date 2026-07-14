"""In-process cache of the instruments alias index, so telegram_listener.py
(a long-running process handling many chat messages) doesn't re-query
instruments on every single inbound message. Refreshed on a TTL, not per
request — instruments rarely change intraday (a new listing is a rare
event, see equity_eod.py), so a several-minute staleness window is an
acceptable trade for not hitting Postgres on every keystroke-speed chat
message.
"""

import time

from ..news.ticker_matching import normalize_name

_TTL_SECONDS = 900

_cache: "AliasCache | None" = None
_cached_at = 0.0


class AliasCache:
    def __init__(self, by_symbol: dict, by_normalized_name: dict):
        self.by_symbol = by_symbol
        self.by_normalized_name = by_normalized_name


def _build(conn) -> AliasCache:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT instrument_id, symbol, name FROM instruments "
            "WHERE exchange = 'NSE' AND instrument_type = 'EQUITY' AND is_active"
        )
        rows = cur.fetchall()

    by_symbol = {}
    by_normalized_name = {}
    for instrument_id, symbol, name in rows:
        entry = {"instrument_id": instrument_id, "symbol": symbol, "name": name}
        by_symbol[symbol.upper()] = entry
        normalized = normalize_name(name or "").lower()
        if normalized:
            by_normalized_name[normalized] = entry
    return AliasCache(by_symbol, by_normalized_name)


def get_alias_cache(conn) -> AliasCache:
    global _cache, _cached_at
    now = time.monotonic()
    if _cache is None or (now - _cached_at) > _TTL_SECONDS:
        _cache = _build(conn)
        _cached_at = now
    return _cache
