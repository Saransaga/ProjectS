"""Short-term (technical/momentum) composite scoring — pure functions, no
I/O. jobs/recommendation_engine.py owns fetching per-instrument data from
technical_indicators_daily/signal_events/relative_strength/fno_oi_buildup
(Domains 1/2/6) plus news_items (Domain 4), bulk_block_deals/
fii_dii_cash_flows (Domain 6) and corporate_calendar (Domain 7), shaping it
into the `inputs` dict score_short_term() expects; see recommendation/
aggregate.py for the shared NULL-vs-0 weighted-average discipline every
component below follows: return None only when the source data genuinely
doesn't exist for this instrument, 0.0 when it exists but found nothing
notable.

All numeric inputs are expected as plain floats, already cast from
psycopg2's Decimal — this package deliberately does no DB I/O and no
Decimal/float arithmetic (mixing the two raises TypeError on arithmetic,
though not on comparison), so the job layer casts at the boundary.
"""

from .aggregate import ComponentResult, aggregate_components

# The original 7 technical/momentum weights are scaled down (x0.7, same
# relative proportions) to make room for 4 new Domain 4/6/7 components below
# — see this domain's plan doc for why short-term (not long-term) is where
# news/bulk-deals/FII-DII/upcoming-events land: all four are short-horizon
# price catalysts, not structural fundamentals.
WEIGHTS = {
    "trend_stack": 0.14,
    "rsi_zone": 0.07,
    "macd_momentum": 0.10,
    "signal_events_recency": 0.14,
    "proximity_52w": 0.07,
    "relative_strength_short": 0.10,
    "fno_positioning": 0.07,
    "news_sentiment": 0.10,
    "bulk_block_deals": 0.08,
    "fii_dii_market_flow": 0.06,
    "upcoming_corporate_events": 0.07,
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


_NEWS_RECENT_DAYS = 2  # full weight within this window, half weight out to the job's full lookback


def _news_sentiment(news_items: list[dict]) -> tuple[float, dict]:
    """news_items: [{"sentiment_score" (-1..1|None), "relevance_score" (0..1),
    "source_credibility_weight", "urgency", "days_ago"}, ...] for this
    instrument in the job's lookback window (see
    RecommendationEngineJob._fetch_news). Always a real 0.0 (never None)
    when empty or nothing has a scored sentiment — "no notable news" is
    itself a valid observation (same convention as signal_events_recency),
    not missing data; Domain 4's keyword-lexicon sentiment is a real, if
    coarse, per-article score, not a guess."""
    if not news_items:
        return 0.0, {"headline_count": 0}

    weighted_sum, total_weight, breaking_count = 0.0, 0.0, 0
    for item in news_items:
        if item.get("urgency") == "BREAKING":
            breaking_count += 1
        if item.get("sentiment_score") is None:
            continue
        decay = 1.0 if item["days_ago"] <= _NEWS_RECENT_DAYS else 0.5
        w = (item.get("relevance_score") or 0.5) * (item.get("source_credibility_weight") or 0.5) * decay
        weighted_sum += item["sentiment_score"] * w
        total_weight += w

    detail = {"headline_count": len(news_items), "breaking_count": breaking_count}
    if total_weight == 0:
        return 0.0, {**detail, "reason": "no scored sentiment among these headlines"}

    avg_sentiment = weighted_sum / total_weight  # -1..1
    detail["avg_sentiment"] = avg_sentiment
    return max(-2.0, min(2.0, avg_sentiment * 2)), detail


def _bulk_block_deals(deals: list[dict]) -> tuple[float, dict]:
    """deals: [{"buy_sell", "quantity"}, ...] for this instrument in the
    job's lookback window (see RecommendationEngineJob._fetch_bulk_block_deals).
    Always a real 0.0 when empty — most instruments have no bulk/block deal
    on most days, that's the normal case, not missing data."""
    if not deals:
        return 0.0, {"deal_count": 0}

    buy_qty = sum(d["quantity"] for d in deals if d["buy_sell"] == "BUY")
    sell_qty = sum(d["quantity"] for d in deals if d["buy_sell"] == "SELL")
    total_qty = buy_qty + sell_qty
    if total_qty == 0:
        return 0.0, {"deal_count": len(deals)}

    net_ratio = (buy_qty - sell_qty) / total_qty  # -1 (all sell) .. 1 (all buy)
    return max(-2.0, min(2.0, net_ratio * 2)), {
        "deal_count": len(deals), "buy_qty": buy_qty, "sell_qty": sell_qty, "net_ratio": net_ratio,
    }


def _fii_dii_market_flow(net_value_cr: float | None) -> tuple[float | None, dict]:
    """net_value_cr: combined FII+DII cash-segment net buy(+)/sell(-) value in
    crores for the most recent flow_date on or before run_date — the same
    market-wide value for every instrument that day (fii_dii_cash_flows is a
    market aggregate, not per-instrument; see RecommendationEngineJob's
    single fetch shared across the whole universe). None only when no
    fii_dii_cash_flows row exists yet for/before this date at all."""
    if net_value_cr is None:
        return None, {"reason": "no fii_dii_cash_flows row on or before this date"}
    if net_value_cr > 3000:
        score = 1.5
    elif net_value_cr > 500:
        score = 0.75
    elif net_value_cr > -500:
        score = 0.0
    elif net_value_cr > -3000:
        score = -0.75
    else:
        score = -1.5
    return score, {"net_value_cr": net_value_cr}


def _upcoming_corporate_events(events: list[dict]) -> tuple[float, dict]:
    """events: [{"event_type"}, ...] from corporate_calendar in the job's
    forward-looking window (see
    RecommendationEngineJob._fetch_upcoming_corporate_events) — a forward
    counterpart to long_term.py's _corporate_actions_signal (which looks
    *backward* at corporate_actions' already-happened ex-dates); same point
    convention, applied to what's *scheduled* instead. EARNINGS/AGM/EGM/
    OTHER carry no inherent direction and score 0 individually (an upcoming
    earnings date is a volatility flag, not a buy/sell signal — deliberately
    not fabricated as one). Always a real 0.0 when empty."""
    _POINTS = {"BUYBACK": 1.0, "BONUS": 0.5, "RIGHTS": -1.0}
    total = sum(_POINTS.get(e["event_type"], 0.0) for e in events)
    return max(-2.0, min(2.0, total)), {"event_types": [e["event_type"] for e in events]}


def score_short_term(inputs: dict) -> dict:
    """inputs keys: technical_indicators (dict|None), macd_hist_prev
    (float|None), trend_events (list[dict]), near_52w_high (bool),
    near_52w_low (bool), rs_rating (float|None), return_1w (float|None),
    return_1m (float|None), has_fno (bool), fno_buildup_type (str|None),
    fno_pcr_oi (float|None), news_items (list[dict]), bulk_block_deals
    (list[dict]), fii_dii_net_value_cr (float|None), upcoming_corporate_events
    (list[dict]). Returns the aggregate.py rationale dict."""
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
    news_score, news_detail = _news_sentiment(inputs.get("news_items", []))
    deals_score, deals_detail = _bulk_block_deals(inputs.get("bulk_block_deals", []))
    fii_dii_score, fii_dii_detail = _fii_dii_market_flow(inputs.get("fii_dii_net_value_cr"))
    events_upcoming_score, events_upcoming_detail = _upcoming_corporate_events(
        inputs.get("upcoming_corporate_events", [])
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
        ComponentResult("news_sentiment", news_score, WEIGHTS["news_sentiment"], news_detail),
        ComponentResult("bulk_block_deals", deals_score, WEIGHTS["bulk_block_deals"], deals_detail),
        ComponentResult(
            "fii_dii_market_flow", fii_dii_score, WEIGHTS["fii_dii_market_flow"], fii_dii_detail,
            counts_toward_gate=False,
        ),
        ComponentResult(
            "upcoming_corporate_events",
            events_upcoming_score,
            WEIGHTS["upcoming_corporate_events"],
            events_upcoming_detail,
        ),
    ]
    return aggregate_components(components)
