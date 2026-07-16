"""Fetches the data telegram_bot/formatting.py needs to render a single
instrument snapshot (/recommend, a bare-text lookup, and each watchlist
digest line) — one on-demand query per call, deliberately not reusing
jobs/recommendation_engine.py's bulk per-universe lookups since the bot only
ever needs one instrument (or the top-N digest) at a time.
"""

from datetime import date, timedelta

_HORIZONS = ("short", "long")
_DIRECTIONS = ("buy", "sell")

# "52-week" low uses a trailing 365-calendar-day window over ohlcv_daily,
# same convention as the NSE/exchange-quoted 52-week high/low.
_LOOKBACK_DAYS = 365
# Only instruments that actually traded in the last week count as
# "currently" near their low — otherwise a stale/delisted instrument whose
# last recorded close happens to be its lowest would show up forever.
_STALE_DAYS = 7
# "Near" the 52-week low, not just the exact tick that set it — a stock
# within this band of its trailing low reads as "trending at" the low to a
# screener user, and an exact-match filter would only ever catch the single
# day the low was actually set. Public (no leading underscore): also used
# by telegram_bot/commands.py to label the /52wlow reply with the same
# threshold actually applied here.
NEAR_LOW_PCT = 3.0


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
    support strictly below — plus the instrument's own latest ATR(14)
    (technical_indicators_daily.atr_14, its recent average daily trading
    range). None when there's no close to anchor against. The
    support_resistance_levels table is fully replaced per instrument on
    every signal_events run (see init.sql's Domain 2 section), so every row
    currently on file for this instrument is already "as of the latest
    run" — no date filter needed there.

    ATR is handed to telegram_bot/formatting.py for two things it cannot do
    without real data: (1) a stock breaking out to a new high has no
    resistance level recorded above it yet (nothing has traded there
    before) — formatting.py falls back to an ATR-multiple price projection
    in that case, clearly labeled as a projection, never presented as an
    observed level; (2) a "how many trading days at the recent pace" rough
    estimate for reaching a target — explicitly a pace, not a forecast of
    if/when a level will actually be hit."""
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

        cur.execute(
            "SELECT atr_14 FROM technical_indicators_daily WHERE instrument_id = %s "
            "ORDER BY trade_date DESC LIMIT 1",
            (instrument_id,),
        )
        row = cur.fetchone()
        atr_14 = float(row[0]) if row and row[0] is not None else None

    return {
        "close": close, "resistance_above": resistance_above, "support_below": support_below, "atr_14": atr_14,
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


def stocks_near_52_week_low(
    conn, limit: int = 10, near_pct: float = NEAR_LOW_PCT
) -> list[dict]:
    """Instruments whose latest close is within `near_pct`% of their own
    trailing-365-day low (over ohlcv_daily.low), ranked closest-to-low
    first. Restricted to instruments that traded within the last
    _STALE_DAYS days, so a stale/delisted instrument's frozen last close
    can't masquerade as "currently" near a low."""
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH bounds AS (
                SELECT instrument_id, min(low) AS low_52w
                FROM ohlcv_daily
                WHERE trade_date >= %s
                GROUP BY instrument_id
            ),
            latest AS (
                SELECT DISTINCT ON (instrument_id) instrument_id, trade_date, close
                FROM ohlcv_daily
                ORDER BY instrument_id, trade_date DESC
            )
            SELECT i.symbol, i.name, l.close, b.low_52w, l.trade_date
            FROM bounds b
            JOIN latest l USING (instrument_id)
            JOIN instruments i USING (instrument_id)
            WHERE l.trade_date >= %s
              AND b.low_52w > 0
              AND l.close <= b.low_52w * (1 + %s / 100.0)
            ORDER BY (l.close - b.low_52w) / b.low_52w ASC
            LIMIT %s
            """,
            (
                date.today() - timedelta(days=_LOOKBACK_DAYS),
                date.today() - timedelta(days=_STALE_DAYS),
                near_pct,
                limit,
            ),
        )
        return [
            {
                "symbol": symbol, "name": name, "close": float(close),
                "low_52w": float(low_52w), "trade_date": trade_date,
                "pct_above_low": (float(close) - float(low_52w)) / float(low_52w) * 100.0,
            }
            for symbol, name, close, low_52w, trade_date in cur.fetchall()
        ]


def top_dividend_yield(conn, limit: int = 10) -> list[dict]:
    """Highest-dividend-yield instruments, one row per instrument (its most
    recent fundamental_ratios.as_of_date), ranked by dividend_yield desc.
    dividend_yield itself is trailing-12-month dividends per share over
    price (see jobs/fundamental_ratios.py), so this already reads as
    "highest dividend paying stocks" rather than a single most-recent
    payout."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT symbol, name, dividend_yield, as_of_date FROM (
                SELECT DISTINCT ON (r.instrument_id)
                    i.symbol, i.name, r.dividend_yield, r.as_of_date
                FROM fundamental_ratios r
                JOIN instruments i USING (instrument_id)
                WHERE r.dividend_yield IS NOT NULL AND r.dividend_yield > 0
                ORDER BY r.instrument_id, r.as_of_date DESC
            ) latest
            ORDER BY dividend_yield DESC
            LIMIT %s
            """,
            (limit,),
        )
        return [
            {
                "symbol": symbol, "name": name,
                "dividend_yield": float(dividend_yield), "as_of_date": as_of_date,
            }
            for symbol, name, dividend_yield, as_of_date in cur.fetchall()
        ]
