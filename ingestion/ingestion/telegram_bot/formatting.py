"""Renders query/snapshot.py's data (and rating_vocabulary buckets) into
Telegram Markdown text. Kept separate from commands.py so the message
*shape* can change without touching dispatch logic, and so
jobs/telegram_alerts.py (the digest/watchlist-change job) can reuse the same
per-instrument formatters commands.py's /recommend uses.

Every function here returns plain text well under Telegram's 4096 UTF-16
code unit cap for a single message (a one-instrument snapshot or a
_DIGEST_TOP_N-bounded digest never gets close) — nothing here truncates or
splits, matching telegram_client.send_message's own documented assumption.
"""

from ..recommendation.rationale_text import top_reasons

_ACTION_EMOJI = {
    "STRONG_BUY": "\U0001F7E2\U0001F7E2",
    "BUY": "\U0001F7E2",
    "HOLD": "\U0001F7E1",
    "SELL": "\U0001F534",
    "STRONG_SELL": "\U0001F534\U0001F534",
}

_MD_SPECIAL = ("\\", "_", "*", "`", "[")


def _esc(text) -> str:
    """Escape legacy-Markdown special chars in dynamic content (symbol/name
    from `instruments`, and free text built from enum values like
    STRONG_BUY/SHORT_BUILDUP/GOLDEN_CROSS that contain a literal
    underscore) before it's interpolated into a hand-built bold/italic
    template. Telegram's parser scans the *whole* message for matching
    entity delimiters — one unescaped `_`/`*`/`` ` ``/`[` anywhere breaks
    parsing (and delivery) of the entire message, not just that value; hit
    live via F&O buildup_type ("SHORT_BUILDUP") in a watchlist alert."""
    text = str(text)
    for ch in _MD_SPECIAL:
        text = text.replace(ch, "\\" + ch)
    return text


def _action_line(label: str, score: float | None, action: str | None) -> str:
    if action is None:
        return f"{label}: insufficient data"
    emoji = _ACTION_EMOJI.get(action, "")
    return f"{label}: {emoji} *{_esc(action)}* (score {score:+.2f})"


# Swing-trading heuristic multiples applied to ATR(14) — the instrument's
# own recent average daily trading range — only as a *fallback* when there's
# no real historical support_resistance_levels row to anchor to (e.g. a
# stock breaking out to a new high has nothing recorded above it yet).
# Target multiple > stop multiple so the projected setup has a >1
# reward:risk ratio, standard practice for an ATR-based target/stop pair.
_ATR_TARGET_MULTIPLE = 2.0
_ATR_STOP_MULTIPLE = 1.5


def _atr_projected_level(close: float, atr_14: float | None, direction: int, multiple: float) -> dict | None:
    """A volatility-based price projection (close +/- multiple*ATR),
    direction=+1 above close/-1 below — used only as a fallback, and always
    flagged `"projected": True` so callers label it differently from a real
    observed support_resistance_levels row."""
    if atr_14 is None or atr_14 <= 0:
        return None
    return {"price": close + direction * multiple * atr_14, "strength": None, "projected": True}


def _pace_estimate(close: float, target_price: float, atr_14: float | None) -> str | None:
    """Distance to target divided by the instrument's own ATR(14) — a rough
    "how many trading days at the recent pace" estimate, deliberately not a
    forecast of *if* or *when* the target will actually be hit (a stock can
    gap there tomorrow or drift sideways for months); framed as a pace, not
    a prediction, and never a fabricated calendar date."""
    if atr_14 is None or atr_14 <= 0:
        return None
    days = abs(target_price - close) / atr_14
    return f"~{max(1, round(days))} trading day(s) at the recent pace (ATR {atr_14:.2f}/day) — a pace estimate, not a forecast"


def _format_price_level(action: str | None, levels: dict | None) -> list[str]:
    """Direction-aware target/exit lines. Prefers a real
    support_resistance_levels row; falls back to an ATR-based projection
    (clearly labeled) only when no real level exists above/below close —
    never a fabricated price, and the pace line is explicitly an estimate,
    not a forecast. For a bullish action the target is above close (upside)
    and the exit trigger is below (where the bullish case breaks); a
    bearish action flips the two. Empty list for HOLD (no directional call
    to hang a target/exit on) or when there's no close/level data yet."""
    if not levels or action not in _ACTION_EMOJI:
        return []
    bullish = action in ("STRONG_BUY", "BUY")
    if not bullish and action not in ("SELL", "STRONG_SELL"):
        return []  # HOLD

    close, atr_14 = levels.get("close"), levels.get("atr_14")
    resistance, support = levels.get("resistance_above"), levels.get("support_below")
    target, guard = (resistance, support) if bullish else (support, resistance)
    target_label = "Target (resistance)" if bullish else "Downside target (support)"
    guard_label = "Exit if it breaks below (support)" if bullish else "Case invalidated above (resistance)"

    if target is None and close is not None:
        target = _atr_projected_level(close, atr_14, 1 if bullish else -1, _ATR_TARGET_MULTIPLE)
        target_label = "Target (no resistance on record — ATR-projected)" if bullish else \
            "Downside target (no support on record — ATR-projected)"
    if guard is None and close is not None:
        guard = _atr_projected_level(close, atr_14, -1 if bullish else 1, _ATR_STOP_MULTIPLE)
        guard_label = "Suggested stop (ATR-projected)" if bullish else "Suggested cover level (ATR-projected)"

    lines = []
    if target:
        touch_txt = f" (touched {target['strength']}x)" if target.get("strength") else ""
        lines.append(f"{target_label}: {target['price']:.2f}{touch_txt}")
        if close is not None:
            pace = _pace_estimate(close, target["price"], atr_14)
            if pace:
                lines.append(f"Est. time to target: {pace}")
    if guard:
        touch_txt = f" (touched {guard['strength']}x)" if guard.get("strength") else ""
        lines.append(f"{guard_label}: {guard['price']:.2f}{touch_txt}")
    if not lines:
        lines.append("No support/resistance level or ATR on record yet to project a target.")
    return lines


def format_recommendation(
    match: dict, rec: dict | None, close: dict | None, levels: dict | None = None, show_watch_tip: bool = True
) -> str:
    """match: {"symbol", "name"}. rec: query.snapshot.latest_recommendation's
    output, or None if the engine hasn't scored this instrument yet.
    close: query.snapshot.latest_close's output, or None. levels:
    query.snapshot.price_levels' output, or None. show_watch_tip: False for
    jobs/telegram_alerts.py's watchlist-alert path — telling an already-
    watching user to /watch the thing they're being alerted on is circular."""
    lines = [f"*{_esc(match['symbol'])}* — {_esc(match['name'])}"]
    if close:
        lines.append(f"Close ({close['trade_date']}): {close['close']:.2f}")
    if rec is None:
        lines.append("No recommendation computed yet for this instrument.")
        return "\n".join(lines)

    lines.append(f"As of {rec['as_of_date']}:")
    lines.append(_action_line("Short-term", rec["short_term_score"], rec["short_term_action"]))
    if rec["short_term_action"] is not None:  # only justify a real action, not "insufficient data"
        for reason in top_reasons(rec.get("short_term_rationale")):
            lines.append(f"  • {_esc(reason)}")
        for price_line in _format_price_level(rec["short_term_action"], levels):
            lines.append(f"  {price_line}")

    lines.append(_action_line("Long-term", rec["long_term_score"], rec["long_term_action"]))
    if rec["long_term_action"] is not None:
        for reason in top_reasons(rec.get("long_term_rationale")):
            lines.append(f"  • {_esc(reason)}")

    if show_watch_tip:
        lines.append("")
        lines.append("Tip: /watch this to get notified if the recommendation changes.")
    return "\n".join(lines)


def format_watchlist(entries: list[dict]) -> str:
    if not entries:
        return "Your watchlist is empty. Add one with `/watch <symbol or company>`."
    lines = ["Your watchlist:"]
    lines += [f"- {_esc(e['symbol'])} ({_esc(e['name'])})" for e in entries]
    return "\n".join(lines)


def format_ambiguous(query: str, candidates: list[dict]) -> str:
    lines = [f"'{_esc(query)}' matches more than one instrument — be more specific:"]
    lines += [f"- {_esc(c['symbol'])} ({_esc(c['name'])})" for c in candidates[:10]]
    return "\n".join(lines)


def format_help() -> str:
    return (
        "Send a stock symbol or company name (e.g. `TCS`, `reliance`) for its "
        "latest short/long-term recommendation.\n\n"
        "Commands:\n"
        "/watch <symbol> — add to your watchlist\n"
        "/unwatch <symbol> — remove from your watchlist\n"
        "/list — show your watchlist\n"
        "/recommend <symbol> — same as sending a bare symbol\n"
        "/top — today's top 5 short-term BUY ideas, with target/exit levels and reasons"
    )


def format_digest_line(entry: dict) -> str:
    """entry: {"symbol", "name", "score", "action"} plus the optional
    "levels"/"rationale" query/snapshot.top_movers now also returns — see
    query/snapshot.top_movers and jobs/telegram_alerts.py, which fetches
    "levels" per entry before calling this (top_movers itself has no close
    price to derive levels from)."""
    emoji = _ACTION_EMOJI.get(entry["action"], "")
    levels = entry.get("levels")
    close = levels.get("close") if levels else None
    price_txt = f" @ {close:.2f}" if close is not None else ""
    lines = [f"{emoji} *{_esc(entry['symbol'])}*{price_txt} {entry['score']:+.2f}"]
    for price_line in _format_price_level(entry["action"], levels):
        lines.append(f"  {price_line}")
    reasons = top_reasons(entry.get("rationale"), limit=1)
    if reasons:
        lines.append(f"  _{_esc(reasons[0])}_")
    return "\n".join(lines)


def format_digest(as_of_date, buys: list[dict], sells: list[dict]) -> str:
    lines = [f"Daily digest — {as_of_date}", "", "Top short-term BUY:"]
    lines += [format_digest_line(e) for e in buys] if buys else ["(none)"]
    lines += ["", "Top short-term SELL:"]
    lines += [format_digest_line(e) for e in sells] if sells else ["(none)"]
    return "\n".join(lines)


def format_top_buys(as_of_date, entries: list[dict]) -> str:
    """entries: query/snapshot.top_movers' output for horizon="short",
    direction="buy", each with "levels" (query/snapshot.price_levels)
    filled in by the caller (see telegram_bot/commands.py's /top handler)."""
    if not entries:
        return f"No short-term BUY ideas as of {as_of_date} yet — check back after the next daily run."
    lines = [f"Top {len(entries)} short-term BUY ideas — {as_of_date}", ""]
    for rank, entry in enumerate(entries, start=1):
        lines.append(f"{rank}. " + format_digest_line(entry).replace("\n", "\n   "))
        lines.append("")
    return "\n".join(lines).rstrip()
