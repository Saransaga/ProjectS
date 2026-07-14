"""Classic futures OI-buildup classification: cross the sign of a contract's
day-over-day price change against its day-over-day OI change. Pure function,
no I/O — same convention as brokerage/classify.py."""


def classify_buildup(price_change_pct: float | None, oi_change_pct: float | None) -> str | None:
    """None when either input is missing, or when price/OI is exactly flat —
    a flat session has no bullish/bearish buildup to report, that's not a
    missing-data gap."""
    if price_change_pct is None or oi_change_pct is None:
        return None
    if price_change_pct > 0 and oi_change_pct > 0:
        return "LONG_BUILDUP"
    if price_change_pct < 0 and oi_change_pct > 0:
        return "SHORT_BUILDUP"
    if price_change_pct < 0 and oi_change_pct < 0:
        return "LONG_UNWINDING"
    if price_change_pct > 0 and oi_change_pct < 0:
        return "SHORT_COVERING"
    return None
