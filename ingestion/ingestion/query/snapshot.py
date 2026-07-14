"""Fetches the data telegram_bot/formatting.py needs to render a single
instrument snapshot (/recommend, a bare-text lookup, and each watchlist
digest line) — one on-demand query per call, deliberately not reusing
jobs/recommendation_engine.py's bulk per-universe lookups since the bot only
ever needs one instrument (or the top-N digest) at a time.
"""

_HORIZONS = ("short", "long")
_DIRECTIONS = ("buy", "sell")


def latest_recommendation(conn, instrument_id: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT as_of_date, short_term_score, short_term_action, short_term_rationale,
                   long_term_score, long_term_action, long_term_rationale
            FROM stock_recommendations
            WHERE instrument_id = %s
            ORDER BY as_of_date DESC
            LIMIT 1
            """,
            (instrument_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    as_of_date, s_score, s_action, s_rationale, l_score, l_action, l_rationale = row
    return {
        "as_of_date": as_of_date,
        "short_term_score": float(s_score) if s_score is not None else None,
        "short_term_action": s_action,
        "short_term_rationale": s_rationale,
        "long_term_score": float(l_score) if l_score is not None else None,
        "long_term_action": l_action,
        "long_term_rationale": l_rationale,
    }


def latest_recommendation_date(conn):
    """Most recent as_of_date with any stock_recommendations rows — powers
    /top, which (unlike TelegramAlertsJob's digest) isn't handed a run_date
    by a scheduled job and has to find "today's" recommendations itself."""
    with conn.cursor() as cur:
        cur.execute("SELECT max(as_of_date) FROM stock_recommendations")
        row = cur.fetchone()
    return row[0] if row else None


def price_levels(conn, instrument_id: int, close: float | None) -> dict | None:
    """Nearest support_resistance_levels rows flanking `close` — the
    strongest (highest pivot touch-count) resistance strictly above and
    support strictly below. None when there's no close to anchor against.
    The table is fully replaced per instrument on every signal_events run
    (see init.sql's Domain 2 section), so every row currently on file for
    this instrument is already "as of the latest run" — no date filter
    needed."""
    if close is None:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            (SELECT 'RESISTANCE', price_level, strength FROM support_resistance_levels
             WHERE instrument_id = %s AND level_type = 'RESISTANCE' AND price_level > %s
             ORDER BY price_level ASC LIMIT 1)
            UNION ALL
            (SELECT 'SUPPORT', price_level, strength FROM support_resistance_levels
             WHERE instrument_id = %s AND level_type = 'SUPPORT' AND price_level < %s
             ORDER BY price_level DESC LIMIT 1)
            """,
            (instrument_id, close, instrument_id, close),
        )
        resistance_above, support_below = None, None
        for level_type, price_level, strength in cur.fetchall():
            level = {"price": float(price_level), "strength": strength}
            if level_type == "RESISTANCE":
                resistance_above = level
            else:
                support_below = level
    return {"close": close, "resistance_above": resistance_above, "support_below": support_below}


def latest_close(conn, instrument_id: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT trade_date, close FROM ohlcv_daily WHERE instrument_id = %s "
            "ORDER BY trade_date DESC LIMIT 1",
            (instrument_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    trade_date, close = row
    return {"trade_date": trade_date, "close": float(close) if close is not None else None}


def top_movers(conn, as_of_date, horizon: str, direction: str, limit: int = 5) -> list[dict]:
    """horizon: 'short'|'long'; direction: 'buy'|'sell' — powers
    TelegramAlertsJob's daily digest ("top N strongest buy/sell"). horizon/
    direction pick the column names interpolated into the query below; both
    are asserted against a small fixed set first (never taken from chat
    input) so that interpolation can't become an injection vector."""
    if horizon not in _HORIZONS:
        raise ValueError(f"horizon must be one of {_HORIZONS}, got {horizon!r}")
    if direction not in _DIRECTIONS:
        raise ValueError(f"direction must be one of {_DIRECTIONS}, got {direction!r}")

    score_col = f"{horizon}_term_score"
    action_col = f"{horizon}_term_action"
    rationale_col = f"{horizon}_term_rationale"
    order = "DESC" if direction == "buy" else "ASC"

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT r.instrument_id, i.symbol, i.name, r.{score_col}, r.{action_col}, r.{rationale_col}
            FROM stock_recommendations r
            JOIN instruments i ON i.instrument_id = r.instrument_id
            WHERE r.as_of_date = %s AND r.{score_col} IS NOT NULL
            ORDER BY r.{score_col} {order}
            LIMIT %s
            """,
            (as_of_date, limit),
        )
        return [
            {
                "instrument_id": instrument_id, "symbol": symbol, "name": name,
                "score": float(score), "action": action, "rationale": rationale,
            }
            for instrument_id, symbol, name, score, action, rationale in cur.fetchall()
        ]
