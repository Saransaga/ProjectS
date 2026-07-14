"""Maps a numeric composite score (-2..+2ish) to the shared 5-level rating
vocabulary. Pure function, no I/O. Thresholds are a first-pass heuristic
(same "expected to need tuning" spirit as this project's other scoring
heuristics, e.g. brokerage/classify.py) — deliberately not symmetric-only
around 0 (STRONG_SELL's threshold is nearer HOLD than STRONG_BUY's, on the
theory that Indian brokerage coverage skews bullish so a genuinely negative
signal is rarer and more informative than an equivalently positive one; easy
to revisit once real output is observed).

Only called on a composite score that survived aggregate.py's
insufficient_data gate — bucketize() itself has no NULL-vs-0 distinction to
make, since aggregate_components() already resolved that upstream."""

from ..rating_vocabulary import RatingBucket


def bucketize(score: float) -> RatingBucket:
    if score >= 1.2:
        return RatingBucket.STRONG_BUY
    if score >= 0.4:
        return RatingBucket.BUY
    if score > -0.4:
        return RatingBucket.HOLD
    if score >= -1.2:
        return RatingBucket.SELL
    return RatingBucket.STRONG_SELL
