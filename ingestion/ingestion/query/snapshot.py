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
            SELECT as_of_date, short_term_score, short_term_action,
                   long_term_score, long_term_action
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
    as_of_date, s_score, s_action, l_score, l_action = row
    return {
        "as_of_date": as_of_date,
        "short_term_score": float(s_score) if s_score is not None else None,
        "short_term_action": s_action,
        "long_term_score": float(l_score) if l_score is not None else None,
        "long_term_action": l_action,
    }


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
    order = "DESC" if direction == "buy" else "ASC"

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT i.symbol, i.name, r.{score_col}, r.{action_col}
            FROM stock_recommendations r
            JOIN instruments i ON i.instrument_id = r.instrument_id
            WHERE r.as_of_date = %s AND r.{score_col} IS NOT NULL
            ORDER BY r.{score_col} {order}
            LIMIT %s
            """,
            (as_of_date, limit),
        )
        return [
            {"symbol": symbol, "name": name, "score": float(score), "action": action}
            for symbol, name, score, action in cur.fetchall()
        ]
