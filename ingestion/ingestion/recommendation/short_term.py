"""Short-term (technical/momentum) composite scoring — pure functions, no
I/O. jobs/recommendation_engine.py owns fetching per-instrument data from
technical_indicators_daily/signal_events/relative_strength/fno_oi_buildup
and shaping it into the `inputs` dict score_short_term() expects; see
recommendation/aggregate.py for the shared NULL-vs-0 weighted-average
discipline every component below follows: return None only when the source
data genuinely doesn't exist for this instrument, 0.0 when it exists but
found nothing notable.

All numeric inputs are expected as plain floats, already cast from
psycopg2's Decimal — this package deliberately does no DB I/O and no
Decimal/float arithmetic (mixing the two raises TypeError on arithmetic,
though not on comparison), so the job layer casts at the boundary.
"""

from .aggregate import ComponentResult, aggregate_components

WEIGHTS = {
    "trend_stack": 0.20,
    "rsi_zone": 0.10,
    "macd_momentum": 0.15,
    "signal_events_recency": 0.20,
    "proximity_52w": 0.10,
    "relative_strength_short": 0.15,
    "fno_positioning": 0.10,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9

# BREAKOUT/BREAKDOWN decay: full weight within this many trading days, half
# weight (still counted, just less emphasized) up to twice that.
_RECENT_DAYS = 5
_STALE_DAYS = 10


def _trend_stack(indicators: dict | None) -> tuple[float | None, dict]:
    """EMA 9/21/50 stack direction + Supertrend agreement.
    indicators: {"ema_9", "ema_21", "ema_50", "supertrend_direction"} or None."""
    if not indicators:
        return None, {"reason": "no technical_indicators_daily row for this instrument/date"}

    ema_9, ema_21, ema_50 = indicators.get("ema_9"), indicators.get("ema_21"), indicators.get("ema_50")
    supertrend = indicators.get("supertrend_direction")
    if ema_9 is None or ema_21 is None or ema_50 is None:
        return None, {"reason": "EMA 9/21/50 not yet computable (insufficient price history)"}

    bullish_stack = ema_9 > ema_21 > ema_50
    bearish_stack = ema_9 < ema_21 < ema_50
    if bullish_stack and supertrend == "UP":
        score = 2.0
    elif bullish_stack:
        score = 1.0
    elif bearish_stack and supertrend == "DOWN":
        score = -2.0
    elif bearish_stack:
        score = -1.0
    else:
        score = 0.0  # mixed/no clean stack — a real, non-notable outcome
    return score, {"ema_9": ema_9, "ema_21": ema_21, "ema_50": ema_50, "supertrend_direction": supertrend}


def _rsi_zone(rsi_14: float | None) -> tuple[float | None, dict]:
    if rsi_14 is None:
        return None, {"reason": "rsi_14 not yet computable (insufficient price history)"}
    if rsi_14 < 30:
        score = 1.5
    elif rsi_14 < 45:
        score = 0.5
    elif rsi_14 <= 55:
        score = 0.0
    elif rsi_14 <= 70:
        score = -0.5
    else:
        score = -1.5
    return score, {"rsi_14": rsi_14}


def _macd_momentum(macd_hist_today: float | None, macd_hist_prev: float | None) -> tuple[float | None, dict]:
    """Histogram (not the raw MACD line) is the right signal here — its
    slope is what "rising/falling momentum" means in standard MACD reading."""
    if macd_hist_today is None or macd_hist_prev is None:
        return None, {"reason": "macd_hist not available for today and/or the prior trading day"}
    rising = macd_hist_today > macd_hist_prev
    if macd_hist_today > 0:
        score = 2.0 if rising else 1.0
    else:
        score = -1.0 if rising else -2.0
    return score, {"macd_hist_today": macd_hist_today, "macd_hist_prev": macd_hist_prev}


def _signal_events_recency(trend_events: list[dict]) -> tuple[float, dict]:
    """trend_events: [{"event_type", "days_ago"}, ...], pre-filtered by the
    job to BREAKOUT/BREAKDOWN/GOLDEN_CROSS/DEATH_CROSS within the trailing
    _STALE_DAYS window. Always returns a real 0.0 (never None) when empty —
    "no breakout happened" is itself a valid, non-missing observation."""
    _POINTS = {"BREAKOUT": 2.0, "BREAKDOWN": -2.0, "GOLDEN_CROSS": 1.5, "DEATH_CROSS": -1.5}
    total = 0.0
    fired = []
    for event in trend_events:
        base = _POINTS.get(event["event_type"])
        if base is None:
            continue
        days_ago = event["days_ago"]
        decay = 1.0 if days_ago <= _RECENT_DAYS else 0.5 if days_ago <= _STALE_DAYS else 0.0
        total += base * decay
        if decay:
            fired.append({"event_type": event["event_type"], "days_ago": days_ago})
    return max(-2.0, min(2.0, total)), {"fired_events": fired}


def _proximity_52w(near_high: bool, near_low: bool) -> tuple[float, dict]:
    if near_high:
        return 1.0, {"proximity": "52W_HIGH"}
    if near_low:
        return -1.0, {"proximity": "52W_LOW"}
    return 0.0, {"proximity": None}


def _relative_strength_short(
    rs_rating: float | None, return_1w: float | None, return_1m: float | None
) -> tuple[float | None, dict]:
    if rs_rating is None:
        return None, {"reason": "no relative_strength row for this instrument/date"}

    if rs_rating >= 80:
        base = 1.5
    elif rs_rating >= 60:
        base = 0.75
    elif rs_rating >= 40:
        base = 0.0
    elif rs_rating >= 20:
        base = -0.75
    else:
        base = -1.5

    adjustment = 0.0
    if return_1w is not None and return_1m is not None:
        same_sign_as_base = (base > 0 and return_1w > 0 and return_1m > 0) or (
            base < 0 and return_1w < 0 and return_1m < 0
        )
        if same_sign_as_base:
            adjustment = 0.5 if base > 0 else -0.5

    score = max(-2.0, min(2.0, base + adjustment))
    return score, {"rs_rating": rs_rating, "return_1w": return_1w, "return_1m": return_1m}


def _fno_positioning(
    has_fno: bool, buildup_type: str | None, pcr_oi: float | None
) -> tuple[float | None, dict]:
    if not has_fno:
        return None, {"reason": "no F&O contract for this underlying"}

    _POINTS = {"LONG_BUILDUP": 1.5, "SHORT_COVERING": 1.0, "LONG_UNWINDING": -1.0, "SHORT_BUILDUP": -1.5}
    score = _POINTS.get(buildup_type, 0.0)  # None/unrecognized buildup_type = flat session, a real 0

    if pcr_oi is not None:
        if pcr_oi > 1.3:
            score += 0.25  # contrarian-bullish read: heavy put OI often means put writers see support
        elif pcr_oi < 0.7:
            score -= 0.25  # contrarian-bearish read: heavy call OI often means call writers see resistance

    return max(-2.0, min(2.0, score)), {"buildup_type": buildup_type, "pcr_oi": pcr_oi}


def score_short_term(inputs: dict) -> dict:
    """inputs keys: technical_indicators (dict|None), macd_hist_prev
    (float|None), trend_events (list[dict]), near_52w_high (bool),
    near_52w_low (bool), rs_rating (float|None), return_1w (float|None),
    return_1m (float|None), has_fno (bool), fno_buildup_type (str|None),
    fno_pcr_oi (float|None). Returns the aggregate.py rationale dict."""
    indicators = inputs.get("technical_indicators")
    trend_score, trend_detail = _trend_stack(indicators)
    rsi_score, rsi_detail = _rsi_zone((indicators or {}).get("rsi_14"))
    macd_score, macd_detail = _macd_momentum(
        (indicators or {}).get("macd_hist"), inputs.get("macd_hist_prev")
    )
    events_score, events_detail = _signal_events_recency(inputs.get("trend_events", []))
    proximity_score, proximity_detail = _proximity_52w(
        inputs.get("near_52w_high", False), inputs.get("near_52w_low", False)
    )
    rs_score, rs_detail = _relative_strength_short(
        inputs.get("rs_rating"), inputs.get("return_1w"), inputs.get("return_1m")
    )
    fno_score, fno_detail = _fno_positioning(
        inputs.get("has_fno", False), inputs.get("fno_buildup_type"), inputs.get("fno_pcr_oi")
    )

    components = [
        ComponentResult("trend_stack", trend_score, WEIGHTS["trend_stack"], trend_detail),
        ComponentResult("rsi_zone", rsi_score, WEIGHTS["rsi_zone"], rsi_detail),
        ComponentResult("macd_momentum", macd_score, WEIGHTS["macd_momentum"], macd_detail),
        ComponentResult("signal_events_recency", events_score, WEIGHTS["signal_events_recency"], events_detail),
        ComponentResult("proximity_52w", proximity_score, WEIGHTS["proximity_52w"], proximity_detail),
        ComponentResult(
            "relative_strength_short", rs_score, WEIGHTS["relative_strength_short"], rs_detail
        ),
        ComponentResult("fno_positioning", fno_score, WEIGHTS["fno_positioning"], fno_detail),
    ]
    return aggregate_components(components)
