"""Maps a brokerage's free-text rating string (e.g. "BUY", "ACCUMULATE",
"REDUCE") to the fixed 5-level STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL scale
used by brokerage_calls.rating_bucket and rating_change_events. Exact match
only (case-insensitive, whitespace-stripped) against a fixed vocabulary of
known Indian-brokerage rating terms — anything unrecognized returns None
rather than guessing, same "fail clearly, don't guess" approach as
fundamentals/xbrl_financial.py's context-selection fallback. Pure function,
no I/O."""

from ..rating_vocabulary import RatingBucket

_RATING_MAP = {
    # STRONG_BUY
    "strong buy": RatingBucket.STRONG_BUY,
    "conviction buy": RatingBucket.STRONG_BUY,
    "top pick": RatingBucket.STRONG_BUY,
    # BUY
    "buy": RatingBucket.BUY,
    "accumulate": RatingBucket.BUY,
    "add": RatingBucket.BUY,
    "outperform": RatingBucket.BUY,
    "overweight": RatingBucket.BUY,
    "positive": RatingBucket.BUY,
    # HOLD
    "hold": RatingBucket.HOLD,
    "neutral": RatingBucket.HOLD,
    "market perform": RatingBucket.HOLD,
    "in-line": RatingBucket.HOLD,
    "in line": RatingBucket.HOLD,
    "equal-weight": RatingBucket.HOLD,
    "equal weight": RatingBucket.HOLD,
    # SELL
    "sell": RatingBucket.SELL,
    "reduce": RatingBucket.SELL,
    "underperform": RatingBucket.SELL,
    "underweight": RatingBucket.SELL,
    "negative": RatingBucket.SELL,
    # STRONG_SELL
    "strong sell": RatingBucket.STRONG_SELL,
}


def classify_rating(raw_rating: str) -> str | None:
    """Map free-text brokerage rating -> STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL,
    or None if `raw_rating` doesn't match a known term."""
    if not raw_rating:
        return None
    return _RATING_MAP.get(raw_rating.strip().lower())
