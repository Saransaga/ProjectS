"""Signal-event detection and pivot-based support/resistance clustering.

These are pure functions over already-fetched history / indicator values —
the calling job owns DB reads/writes and timestamps events with run_date.
"""

import pandas as pd

PROXIMITY_52W_PCT = 2.0
BREAKOUT_LOOKBACK_DAYS = 20
BREAKOUT_VOLUME_MULTIPLIER = 1.5
WEEKS_52_TRADING_DAYS = 252

PIVOT_WINDOW = 3  # bars on each side that must be lower/higher for a swing point
CLUSTER_TOLERANCE_PCT = 0.75  # merge pivot prices within this % of each other
TOP_K_LEVELS = 5  # per side (support / resistance)

# Below this many trading days, a "52-week high/low" is a trivial artifact of
# having barely any history (e.g. day 1 of a newly listed stock: high == low
# == the only close, so it's "within 2%" of both by definition) rather than a
# meaningful proximity signal.
MIN_HISTORY_FOR_52W = 20


def detect_golden_death_cross(prev_sma_50, prev_sma_200, curr_sma_50, curr_sma_200) -> str | None:
    if None in (prev_sma_50, prev_sma_200, curr_sma_50, curr_sma_200):
        return None
    was_below = prev_sma_50 <= prev_sma_200
    is_above = curr_sma_50 > curr_sma_200
    if was_below and is_above:
        return "GOLDEN_CROSS"
    was_above = prev_sma_50 >= prev_sma_200
    is_below = curr_sma_50 < curr_sma_200
    if was_above and is_below:
        return "DEATH_CROSS"
    return None


def detect_52w_proximity(df: pd.DataFrame) -> list[dict]:
    """df: chronological OHLC history ending at the date being evaluated."""
    if len(df) < MIN_HISTORY_FOR_52W:
        return []

    window = df.tail(WEEKS_52_TRADING_DAYS)
    close = df["close"].iloc[-1]

    events = []
    high_52w = window["high"].max()
    high_date = window["high"].idxmax()
    if high_52w > 0:
        pct_from_high = (high_52w - close) / high_52w * 100
        if pct_from_high <= PROXIMITY_52W_PCT:
            events.append(
                {
                    "event_type": "HIGH_52W_PROXIMITY",
                    "details": {
                        "close": round(float(close), 4),
                        "week_52_high": round(float(high_52w), 4),
                        "high_date": high_date.isoformat(),
                        "pct_from_high": round(float(pct_from_high), 4),
                    },
                }
            )

    low_52w = window["low"].min()
    low_date = window["low"].idxmin()
    if low_52w > 0:
        pct_from_low = (close - low_52w) / low_52w * 100
        if pct_from_low <= PROXIMITY_52W_PCT:
            events.append(
                {
                    "event_type": "LOW_52W_PROXIMITY",
                    "details": {
                        "close": round(float(close), 4),
                        "week_52_low": round(float(low_52w), 4),
                        "low_date": low_date.isoformat(),
                        "pct_from_low": round(float(pct_from_low), 4),
                    },
                }
            )

    return events


def detect_breakout_breakdown(df: pd.DataFrame) -> dict | None:
    """Close beyond the prior N-day close range on above-average volume."""
    if len(df) < BREAKOUT_LOOKBACK_DAYS + 1:
        return None

    today = df.iloc[-1]
    prior = df.iloc[-(BREAKOUT_LOOKBACK_DAYS + 1) : -1]
    prior_high = prior["close"].max()
    prior_low = prior["close"].min()
    avg_volume = prior["volume"].mean()

    if avg_volume <= 0 or today["volume"] <= BREAKOUT_VOLUME_MULTIPLIER * avg_volume:
        return None

    volume_ratio = today["volume"] / avg_volume
    if today["close"] > prior_high:
        return {
            "event_type": "BREAKOUT",
            "details": {
                "close": round(float(today["close"]), 4),
                "prior_high": round(float(prior_high), 4),
                "lookback_days": BREAKOUT_LOOKBACK_DAYS,
                "volume": int(today["volume"]),
                "avg_volume": round(float(avg_volume), 2),
                "volume_ratio": round(float(volume_ratio), 2),
            },
        }
    if today["close"] < prior_low:
        return {
            "event_type": "BREAKDOWN",
            "details": {
                "close": round(float(today["close"]), 4),
                "prior_low": round(float(prior_low), 4),
                "lookback_days": BREAKOUT_LOOKBACK_DAYS,
                "volume": int(today["volume"]),
                "avg_volume": round(float(avg_volume), 2),
                "volume_ratio": round(float(volume_ratio), 2),
            },
        }
    return None


def _find_pivots(df: pd.DataFrame) -> list[tuple]:
    """Local swing highs/lows: a bar is a pivot if its high/low is the
    extreme of a centered window of PIVOT_WINDOW bars on each side."""
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    dates = df.index
    n = len(df)

    pivots = []
    for i in range(PIVOT_WINDOW, n - PIVOT_WINDOW):
        window_highs = highs[i - PIVOT_WINDOW : i + PIVOT_WINDOW + 1]
        window_lows = lows[i - PIVOT_WINDOW : i + PIVOT_WINDOW + 1]
        if highs[i] == window_highs.max():
            pivots.append((dates[i], float(highs[i])))
        if lows[i] == window_lows.min():
            pivots.append((dates[i], float(lows[i])))
    return pivots


def compute_support_resistance(df: pd.DataFrame) -> list[dict]:
    """Cluster swing-point prices into support/resistance levels, ranked by
    touch count (strength). Classified relative to the latest close."""
    current_close = float(df["close"].iloc[-1])
    pivots = sorted(_find_pivots(df), key=lambda p: p[1])
    if not pivots:
        return []

    clusters: list[list[tuple]] = []
    for point in pivots:
        if clusters and abs(point[1] - clusters[-1][-1][1]) / clusters[-1][-1][1] * 100 <= CLUSTER_TOLERANCE_PCT:
            clusters[-1].append(point)
        else:
            clusters.append([point])

    levels = []
    for cluster in clusters:
        prices = [p[1] for p in cluster]
        dates = [p[0] for p in cluster]
        level_price = sum(prices) / len(prices)
        levels.append(
            {
                "level_type": "SUPPORT" if level_price < current_close else "RESISTANCE",
                "price_level": round(level_price, 4),
                "strength": len(cluster),
                "first_touch_date": min(dates),
                "last_touch_date": max(dates),
            }
        )

    support = sorted((lv for lv in levels if lv["level_type"] == "SUPPORT"), key=lambda lv: -lv["strength"])
    resistance = sorted((lv for lv in levels if lv["level_type"] == "RESISTANCE"), key=lambda lv: -lv["strength"])
    return support[:TOP_K_LEVELS] + resistance[:TOP_K_LEVELS]
