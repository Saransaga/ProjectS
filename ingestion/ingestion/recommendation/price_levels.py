"""Direction-aware price target/stop resolution — pure, no I/O. Extracted out
of telegram_bot/formatting.py so both the Telegram bot and
jobs/recommendation_outcomes.py (which needs the exact same target/stop a user
would have seen on the day a call was made) share one implementation instead
of two copies drifting apart.

Prefers a real support_resistance_levels row (via query/snapshot.py's
price_levels()); falls back to an ATR(14)-based projection only when no real
level exists above/below close (e.g. a stock breaking out to a new high has
nothing recorded above it yet) — always flagged `projected: True` so callers
can label it differently from an observed level, never presenting a fabricated
price as real.
"""

# Swing-trading heuristic multiples applied to ATR(14) — the instrument's own
# recent average daily trading range — only as a fallback. Target multiple >
# stop multiple so the projected setup has a >1 reward:risk ratio, standard
# practice for an ATR-based target/stop pair.
_ATR_TARGET_MULTIPLE = 2.0
_ATR_STOP_MULTIPLE = 1.5


def atr_projected_level(close: float, atr_14: float | None, direction: int, multiple: float) -> dict | None:
    """A volatility-based price projection (close +/- multiple*ATR),
    direction=+1 above close/-1 below — used only as a fallback, and always
    flagged `"projected": True` so callers label it differently from a real
    observed support_resistance_levels row."""
    if atr_14 is None or atr_14 <= 0:
        return None
    return {"price": close + direction * multiple * atr_14, "strength": None, "projected": True}


def pace_estimate_days(close: float, target_price: float, atr_14: float | None) -> float | None:
    """Distance to target divided by the instrument's own ATR(14) — a rough
    "how many trading days at the recent pace" estimate, deliberately not a
    forecast of *if* or *when* the target will actually be hit. Returns raw
    days (float); callers own their own text formatting."""
    if atr_14 is None or atr_14 <= 0:
        return None
    return abs(target_price - close) / atr_14


def resolve_price_targets(action: str | None, levels: dict | None) -> dict:
    """Resolves the target/stop pair for a given action + query/snapshot.py's
    price_levels() output. Returns {"target": {...} | None, "stop": {...} |
    None}, each a dict shaped {"price", "strength", "projected"} (real levels
    have "projected": False and a touch-count "strength"; ATR-projected
    fallbacks have "projected": True and "strength": None).

    Empty dict values (None/None) for HOLD (no directional call to hang a
    target/stop on), an unrecognized action, or when there's no close/level
    data yet to project from."""
    if not levels or action not in ("STRONG_BUY", "BUY", "SELL", "STRONG_SELL"):
        return {"target": None, "stop": None}

    bullish = action in ("STRONG_BUY", "BUY")
    close, atr_14 = levels.get("close"), levels.get("atr_14")
    resistance, support = levels.get("resistance_above"), levels.get("support_below")
    target, guard = (resistance, support) if bullish else (support, resistance)

    if target is not None:
        target = {**target, "projected": False}
    elif close is not None:
        target = atr_projected_level(close, atr_14, 1 if bullish else -1, _ATR_TARGET_MULTIPLE)

    if guard is not None:
        guard = {**guard, "projected": False}
    elif close is not None:
        guard = atr_projected_level(close, atr_14, -1 if bullish else 1, _ATR_STOP_MULTIPLE)

    return {"target": target, "stop": guard}
