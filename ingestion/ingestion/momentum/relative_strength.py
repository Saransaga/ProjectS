"""Trailing total return + IBD-style relative-strength percentile ranking.
Pure functions over already-fetched OHLCV history (pandas DataFrames from
analytics.history.fetch_lookback_history) and a composite-score map — the
calling job (jobs/relative_strength.py) owns the DB read/write.

Windows are expressed in trading days, not calendar days — same convention
already used elsewhere in this codebase (analytics/signals.py's
WEEKS_52_TRADING_DAYS = 252 for "52-week" high/low) rather than a strict
calendar lookup, since trade_date history has no row on non-trading days
to look up anyway.
"""

RETURN_WINDOWS = {
    "1w": 5,
    "1m": 21,
    "3m": 63,
    "6m": 126,
    "1y": 252,
}

# IBD's official RS Rating composite weights 3/6/9/12-month returns
# 40/20/20/20. This phase doesn't otherwise need a 9-month return anywhere,
# so the composite is reweighted 40/30/30 over the 3/6/12-month windows it
# does store — a simplification, not the official formula. Documented here
# and in init.sql's relative_strength comment.
_RS_COMPOSITE_WEIGHTS = {"3m": 0.4, "6m": 0.3, "1y": 0.3}

# IBD's scale is a 1-99 percentile rank, not a 0-100 one.
_RS_RATING_MIN = 1
_RS_RATING_MAX = 99


def compute_return_pct(df, trading_days: int) -> float | None:
    """% change in close from `trading_days` bars ago to the most recent bar.
    None if there isn't enough history yet or the base price is zero."""
    if len(df) <= trading_days:
        return None
    close_now = float(df["close"].iloc[-1])
    close_then = float(df["close"].iloc[-(trading_days + 1)])
    if close_then == 0:
        return None
    return (close_now / close_then - 1) * 100


def compute_returns(df) -> dict[str, float | None]:
    """{"1w": ..., "1m": ..., "3m": ..., "6m": ..., "1y": ...} trailing total
    returns for one instrument's history."""
    return {label: compute_return_pct(df, days) for label, days in RETURN_WINDOWS.items()}


def compute_composite_score(returns: dict[str, float | None]) -> float | None:
    """Weighted blend of 3M/6M/1Y returns (see module docstring). None if any
    of the three windows lacks enough history — a partial composite would
    silently over-weight whichever windows happen to be available."""
    values = [returns.get(w) for w in _RS_COMPOSITE_WEIGHTS]
    if any(v is None for v in values):
        return None
    return sum(returns[w] * weight for w, weight in _RS_COMPOSITE_WEIGHTS.items())


def compute_rs_ratings(composite_scores: dict[int, float]) -> dict[int, int]:
    """IBD-style 1-99 percentile rank of each instrument_id's composite score
    against every other instrument in `composite_scores` (the day's whole
    rated universe). Ties get the same rank (average-rank percentile, not an
    arbitrary tiebreak by insertion order)."""
    if not composite_scores:
        return {}

    n = len(composite_scores)
    if n == 1:
        return {next(iter(composite_scores)): _RS_RATING_MAX}

    sorted_ids = sorted(composite_scores, key=lambda k: composite_scores[k])
    # Average rank (0-indexed) per distinct score value, so tied scores share
    # a rating instead of an arbitrary sort-order-dependent split.
    ranks: dict[int, float] = {}
    i = 0
    while i < n:
        j = i
        while j < n and composite_scores[sorted_ids[j]] == composite_scores[sorted_ids[i]]:
            j += 1
        avg_rank = (i + j - 1) / 2
        for k in range(i, j):
            ranks[sorted_ids[k]] = avg_rank
        i = j

    return {
        instrument_id: round(_RS_RATING_MIN + (rank / (n - 1)) * (_RS_RATING_MAX - _RS_RATING_MIN))
        for instrument_id, rank in ranks.items()
    }
