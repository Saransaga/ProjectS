"""Valuation ratios computed weekly from stored fundamentals + latest price +
trailing dividends. Pure functions — the calling job owns fetching the inputs
and persisting the output (same style as analytics/signals.py)."""


def trailing_sum(quarterly_values: list[float | None], n: int = 4) -> float | None:
    """Sum of the most recent n quarters, or None if fewer than n are present
    (avoids understating trailing-12m figures from partial data)."""
    recent = quarterly_values[-n:]
    if len(recent) < n or any(v is None for v in recent):
        return None
    return sum(recent)


def compute_pe_ratio(price: float, trailing_eps: float | None) -> float | None:
    if not trailing_eps or trailing_eps <= 0:
        return None
    return price / trailing_eps


def compute_ps_ratio(price: float, shares_outstanding: int | None, trailing_revenue: float | None) -> float | None:
    if not shares_outstanding or not trailing_revenue or trailing_revenue <= 0:
        return None
    market_cap = price * shares_outstanding
    return market_cap / trailing_revenue


def compute_dividend_yield(price: float, trailing_dividends_per_share: float) -> float | None:
    if price <= 0:
        return None
    return trailing_dividends_per_share / price * 100


def compute_payout_ratio(trailing_dividends_per_share: float, trailing_eps: float | None) -> float | None:
    if not trailing_eps or trailing_eps <= 0:
        return None
    return trailing_dividends_per_share / trailing_eps * 100
