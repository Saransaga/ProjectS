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


def _format_price_level(action: str | None, levels: dict | None) -> str | None:
    """Direction-aware target/exit line built only from real
    support_resistance_levels rows + the latest close — never a fabricated
    price or date. For a bullish action the target is the nearest
    resistance above (upside) and the exit trigger is the nearest support
    below (where the bullish case breaks); a bearish action flips the two.
    None for HOLD (no directional call to hang a target/exit on) or when
    there's no close/level data yet."""
    if not levels or action not in _ACTION_EMOJI:
        return None
    bullish = action in ("STRONG_BUY", "BUY")
    if not bullish and action not in ("SELL", "STRONG_SELL"):
        return None  # HOLD

    resistance, support = levels.get("resistance_above"), levels.get("support_below")
    target, guard = (resistance, support) if bullish else (support, resistance)
    target_label = "Target (resistance)" if bullish else "Downside target (support)"
    guard_label = "Exit if it breaks below (support)" if bullish else "Case invalidated above (resistance)"

    parts = []
    if target:
        parts.append(f"{target_label}: {target['price']:.2f} (touched {target['strength']}x)")
    if guard:
        parts.append(f"{guard_label}: {guard['price']:.2f} (touched {guard['strength']}x)")
    return " · ".join(parts) if parts else "No nearby support/resistance level on record yet."


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
        price_line = _format_price_level(rec["short_term_action"], levels)
        if price_line:
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
    lines = [f"{emoji} *{_esc(entry['symbol'])}* {entry['score']:+.2f}"]
    price_line = _format_price_level(entry["action"], entry.get("levels"))
    if price_line:
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
