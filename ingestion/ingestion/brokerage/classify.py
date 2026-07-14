"""Maps a brokerage's free-text rating string (e.g. "BUY", "ACCUMULATE",
"REDUCE") to the fixed 5-level STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL scale
used by brokerage_calls.rating_bucket and rating_change_events. Exact match
only (case-insensitive, whitespace-stripped) against a fixed vocabulary of
known Indian-brokerage rating terms — anything unrecognized returns None
rather than guessing, same "fail clearly, don't guess" approach as
fundamentals/xbrl_financial.py's context-selection fallback. Pure function,
no I/O."""

_RATING_MAP = {
    # STRONG_BUY
    "strong buy": "STRONG_BUY",
    "conviction buy": "STRONG_BUY",
    "top pick": "STRONG_BUY",
    # BUY
    "buy": "BUY",
    "accumulate": "BUY",
    "add": "BUY",
    "outperform": "BUY",
    "overweight": "BUY",
    "positive": "BUY",
    # HOLD
    "hold": "HOLD",
    "neutral": "HOLD",
    "market perform": "HOLD",
    "in-line": "HOLD",
    "in line": "HOLD",
    "equal-weight": "HOLD",
    "equal weight": "HOLD",
    # SELL
    "sell": "SELL",
    "reduce": "SELL",
    "underperform": "SELL",
    "underweight": "SELL",
    "negative": "SELL",
    # STRONG_SELL
    "strong sell": "STRONG_SELL",
}


def classify_rating(raw_rating: str) -> str | None:
    """Map free-text brokerage rating -> STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL,
    or None if `raw_rating` doesn't match a known term."""
    if not raw_rating:
        return None
    return _RATING_MAP.get(raw_rating.strip().lower())
