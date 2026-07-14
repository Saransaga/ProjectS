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

_ACTION_EMOJI = {
    "STRONG_BUY": "\U0001F7E2\U0001F7E2",
    "BUY": "\U0001F7E2",
    "HOLD": "\U0001F7E1",
    "SELL": "\U0001F534",
    "STRONG_SELL": "\U0001F534\U0001F534",
}


def _action_line(label: str, score: float | None, action: str | None) -> str:
    if action is None:
        return f"{label}: insufficient data"
    emoji = _ACTION_EMOJI.get(action, "")
    return f"{label}: {emoji} *{action}* (score {score:+.2f})"


def format_recommendation(match: dict, rec: dict | None, close: dict | None) -> str:
    """match: {"symbol", "name"}. rec: query.snapshot.latest_recommendation's
    output, or None if the engine hasn't scored this instrument yet.
    close: query.snapshot.latest_close's output, or None."""
    lines = [f"*{match['symbol']}* — {match['name']}"]
    if close:
        lines.append(f"Close ({close['trade_date']}): {close['close']:.2f}")
    if rec is None:
        lines.append("No recommendation computed yet for this instrument.")
        return "\n".join(lines)

    lines.append(f"As of {rec['as_of_date']}:")
    lines.append(_action_line("Short-term", rec["short_term_score"], rec["short_term_action"]))
    lines.append(_action_line("Long-term", rec["long_term_score"], rec["long_term_action"]))
    return "\n".join(lines)


def format_watchlist(entries: list[dict]) -> str:
    if not entries:
        return "Your watchlist is empty. Add one with `/watch <symbol or company>`."
    lines = ["Your watchlist:"]
    lines += [f"- {e['symbol']} ({e['name']})" for e in entries]
    return "\n".join(lines)


def format_ambiguous(query: str, candidates: list[dict]) -> str:
    lines = [f"{query!r} matches more than one instrument — be more specific:"]
    lines += [f"- {c['symbol']} ({c['name']})" for c in candidates[:10]]
    return "\n".join(lines)


def format_help() -> str:
    return (
        "Send a stock symbol or company name (e.g. `TCS`, `reliance`) for its "
        "latest short/long-term recommendation.\n\n"
        "Commands:\n"
        "/watch <symbol> — add to your watchlist\n"
        "/unwatch <symbol> — remove from your watchlist\n"
        "/list — show your watchlist\n"
        "/recommend <symbol> — same as sending a bare symbol"
    )


def format_digest_line(entry: dict) -> str:
    """entry: {"symbol", "name", "score", "action"} — see
    query/snapshot.top_movers."""
    emoji = _ACTION_EMOJI.get(entry["action"], "")
    return f"{emoji} *{entry['symbol']}* {entry['score']:+.2f}"


def format_digest(as_of_date, buys: list[dict], sells: list[dict]) -> str:
    lines = [f"Daily digest — {as_of_date}", "", "Top short-term BUY:"]
    lines += [format_digest_line(e) for e in buys] if buys else ["(none)"]
    lines += ["", "Top short-term SELL:"]
    lines += [format_digest_line(e) for e in sells] if sells else ["(none)"]
    return "\n".join(lines)
