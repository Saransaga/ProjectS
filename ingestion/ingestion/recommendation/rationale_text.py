"""Turns a short_term.py/long_term.py rationale dict (aggregate.py's shape)
into short, human-readable justification lines for the Telegram bot — pure
formatting, no I/O. Picks the components with the largest |weighted|
contribution so a reply stays short instead of dumping all 6-7 subscores;
one renderer per component name, using its own `detail` shape (see
short_term.py/long_term.py's ComponentResult calls for what each one holds).
"""


def _trend_stack(detail: dict) -> str:
    if "reason" in detail:
        return "Trend: " + detail["reason"]
    ema_9, ema_21, ema_50 = detail["ema_9"], detail["ema_21"], detail["ema_50"]
    if ema_9 > ema_21 > ema_50:
        stack = "bullish EMA stack (9>21>50)"
    elif ema_9 < ema_21 < ema_50:
        stack = "bearish EMA stack (9<21<50)"
    else:
        stack = "mixed EMA stack"
    supertrend = detail.get("supertrend_direction")
    return f"Trend: {stack}" + (f", Supertrend {supertrend}" if supertrend else "")


def _rsi_zone(detail: dict) -> str:
    if "reason" in detail:
        return "RSI: " + detail["reason"]
    rsi = detail["rsi_14"]
    zone = (
        "oversold" if rsi < 30 else "weak" if rsi < 45 else "neutral"
        if rsi <= 55 else "strong" if rsi <= 70 else "overbought"
    )
    return f"RSI(14) {rsi:.0f} — {zone}"


def _macd_momentum(detail: dict) -> str:
    if "reason" in detail:
        return "MACD: " + detail["reason"]
    today, prev = detail["macd_hist_today"], detail["macd_hist_prev"]
    side = "above" if today > 0 else "below"
    direction = "rising" if today > prev else "falling"
    return f"MACD histogram {side} zero and {direction}"


def _signal_events_recency(detail: dict) -> str:
    fired = detail.get("fired_events") or []
    if not fired:
        return "No recent breakout/breakdown/cross signal"
    return "Signal: " + ", ".join(f"{e['event_type']} {e['days_ago']}d ago" for e in fired)


def _proximity_52w(detail: dict) -> str:
    proximity = detail.get("proximity")
    if proximity == "52W_HIGH":
        return "Trading near its 52-week high"
    if proximity == "52W_LOW":
        return "Trading near its 52-week low"
    return "Not near its 52-week high/low"


def _relative_strength(detail: dict) -> str:
    if "reason" in detail:
        return "Relative strength: " + detail["reason"]
    return f"Relative strength rating {detail['rs_rating']:.0f}/100 vs the broader market"


def _fno_positioning(detail: dict) -> str:
    if "reason" in detail:
        return "F&O: " + detail["reason"]
    buildup = detail.get("buildup_type") or "flat session"
    pcr = detail.get("pcr_oi")
    return f"F&O positioning: {buildup}" + (f", PCR {pcr:.2f}" if pcr is not None else "")


def _eps_growth(detail: dict) -> str:
    if "reason" in detail:
        return "Earnings: " + detail["reason"]
    return f"EPS growth {detail['eps_growth_pct']:+.1f}% ({detail['basis']})"


def _valuation_pe(detail: dict) -> str:
    if "reason" in detail:
        return "Valuation: " + detail["reason"]
    return f"P/E {detail['pe_ratio']:.1f}"


def _shareholding_trend(detail: dict) -> str:
    if "reason" in detail:
        return "Shareholding: " + detail["reason"]
    parts = []
    if "promoter_pct_delta" in detail:
        parts.append(f"promoter holding {detail['promoter_pct_delta']:+.2f}pp")
    if "fii_pct_delta" in detail:
        parts.append(f"FII holding {detail['fii_pct_delta']:+.2f}pp")
    if "pledged_promoter_pct_delta" in detail:
        parts.append(f"pledged shares {detail['pledged_promoter_pct_delta']:+.2f}pp")
    return "Shareholding: " + (", ".join(parts) if parts else "no notable change")


def _consensus_signal(detail: dict) -> str:
    if "reason" in detail:
        return "Analyst consensus: " + detail["reason"]
    upside = detail.get("implied_upside_pct")
    return f"Analyst consensus: {detail['consensus_rating_bucket']}" + (
        f", {upside:+.1f}% implied upside" if upside is not None else ""
    )


def _corporate_actions_signal(detail: dict) -> str:
    types = detail.get("action_types") or []
    return f"Corporate actions (12mo): {', '.join(types)}" if types else "No corporate actions in the last 12 months"


def _news_sentiment(detail: dict) -> str:
    count = detail.get("headline_count", 0)
    if count == 0:
        return "News: no recent headlines"
    if "avg_sentiment" not in detail:
        return f"News: {count} recent headline(s), none with a scored sentiment"
    tone = "positive" if detail["avg_sentiment"] > 0.15 else "negative" if detail["avg_sentiment"] < -0.15 else "mixed/neutral"
    breaking = f", {detail['breaking_count']} breaking" if detail.get("breaking_count") else ""
    return f"News: {count} recent headline(s), {tone} tone{breaking}"


def _bulk_block_deals(detail: dict) -> str:
    count = detail.get("deal_count", 0)
    if count == 0:
        return "No bulk/block deals recently"
    if "net_ratio" not in detail:
        return f"{count} bulk/block deal(s) recently, no net quantity"
    lean = "buy-side" if detail["net_ratio"] > 0.1 else "sell-side" if detail["net_ratio"] < -0.1 else "balanced"
    return f"Bulk/block deals: {count} recently, {lean}"


def _fii_dii_market_flow(detail: dict) -> str:
    if "reason" in detail:
        return "FII/DII flow: " + detail["reason"]
    net = detail["net_value_cr"]
    direction = "net inflow" if net > 0 else "net outflow" if net < 0 else "flat"
    return f"Market-wide FII/DII {direction}: {net:+.0f} cr"


def _upcoming_corporate_events(detail: dict) -> str:
    types = detail.get("event_types") or []
    return f"Upcoming corporate events: {', '.join(types)}" if types else "No upcoming corporate events on record"


_RENDERERS = {
    "trend_stack": _trend_stack,
    "rsi_zone": _rsi_zone,
    "macd_momentum": _macd_momentum,
    "signal_events_recency": _signal_events_recency,
    "proximity_52w": _proximity_52w,
    "relative_strength_short": _relative_strength,
    "relative_strength_long": _relative_strength,
    "fno_positioning": _fno_positioning,
    "eps_growth": _eps_growth,
    "valuation_pe": _valuation_pe,
    "shareholding_trend": _shareholding_trend,
    "consensus_signal": _consensus_signal,
    "corporate_actions_signal": _corporate_actions_signal,
    "news_sentiment": _news_sentiment,
    "bulk_block_deals": _bulk_block_deals,
    "fii_dii_market_flow": _fii_dii_market_flow,
    "upcoming_corporate_events": _upcoming_corporate_events,
}


def _scored_components(rationale: dict | None) -> list[dict]:
    """Components with a real (non-None) weighted contribution, largest
    |weighted| first — the shared selection logic behind top_reasons() and
    dominant_component_name()."""
    if not rationale:
        return []
    scored = [c for c in rationale.get("components", []) if c.get("weighted") is not None]
    scored.sort(key=lambda c: abs(c["weighted"]), reverse=True)
    return scored


def top_reasons(rationale: dict | None, limit: int = 3) -> list[str]:
    """The `limit` components with the largest |weighted| contribution
    (components with no data, i.e. weighted is None, are excluded — same
    NULL-vs-0 discipline as aggregate.py), each rendered via its
    component-specific formatter. Empty list when rationale is None/empty or
    every component is unavailable."""
    scored = _scored_components(rationale)
    return [_RENDERERS.get(c["name"], lambda d, n=c["name"], s=c["subscore"]: f"{n}: {s:+.2f}")(c["detail"]) for c in scored[:limit]]


def dominant_component_name(rationale: dict | None) -> str | None:
    """The single component name (not rendered text) with the largest
    |weighted| contribution — used by jobs/recommendation_outcomes.py to tag
    each tracked call with which signal drove it, for "accuracy by dominant
    signal" reporting. None when every component is unavailable."""
    scored = _scored_components(rationale)
    return scored[0]["name"] if scored else None
