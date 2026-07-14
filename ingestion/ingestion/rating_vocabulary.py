"""Shared 5-level rating vocabulary used across brokerage consensus (Domain 5)
and the recommendation engine (Domain 8) — one source of truth instead of
independent copies of the same 5 strings scattered across modules.

Inherits from str so members compare equal to, hash like, and serialize as
plain strings: they drop straight into psycopg2 query params and the
existing CHECK (... IN ('STRONG_BUY', ...)) columns with no .value
unwrapping anywhere a plain string was used before. A typo in a member name
now fails at import time instead of silently producing a value the CHECK
constraint would reject at insert time.
"""

from enum import Enum


class RatingBucket(str, Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


# Most bullish first — used to tie-break compute_consensus_bucket and to
# bucketize a numeric composite score (recommendation/bucketize.py).
BUCKET_ORDER = [
    RatingBucket.STRONG_BUY,
    RatingBucket.BUY,
    RatingBucket.HOLD,
    RatingBucket.SELL,
    RatingBucket.STRONG_SELL,
]
