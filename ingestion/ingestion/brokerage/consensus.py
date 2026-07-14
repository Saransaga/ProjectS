"""Pure consensus-aggregation math for Domain 5's consensus_ratings table —
the calling job (jobs/consensus_ratings.py) owns fetching the deduped,
trailing-window brokerage_calls rows and persisting the output (same
separation as fundamentals/ratios.py)."""

from collections import Counter

from ..rating_vocabulary import BUCKET_ORDER


def compute_consensus_bucket(rating_buckets: list[str]) -> str | None:
    """Majority vote across a deduped (one-per-brokerage) set of rating
    buckets. Ties are broken toward the more bullish bucket (STRONG_BUY >
    BUY > HOLD > SELL > STRONG_SELL) — a deliberate choice, not an arbitrary
    one: on a tie there's no statistical basis to prefer the bearish read,
    and analysts skew toward publishing/maintaining buy-side coverage, so
    ties-to-bullish is the less surprising default for a summary field.
    Returns None for an empty input (no rated calls in the window)."""
    buckets = [b for b in rating_buckets if b]
    if not buckets:
        return None

    counts = Counter(buckets)
    max_count = max(counts.values())
    tied = [b for b in counts if counts[b] == max_count]
    return min(tied, key=lambda b: BUCKET_ORDER.index(b))
