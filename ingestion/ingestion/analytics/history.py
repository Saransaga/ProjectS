from datetime import date, timedelta

import pandas as pd

# Covers the longest lookback we need (252-trading-day 52-week high/low, 200-period
# EMA/SMA) plus a warm-up buffer so those long indicators have settled rather than
# just barely having their first non-null value.
LOOKBACK_CALENDAR_DAYS = 450


def fetch_lookback_history(conn, run_date: date) -> dict[int, pd.DataFrame]:
    """One bulk query for every instrument's OHLCV history ending at run_date,
    grouped into a per-instrument DataFrame (chronological, indexed by trade_date).
    Only instruments with a row on run_date itself are included."""
    start = run_date - timedelta(days=LOOKBACK_CALENDAR_DAYS)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT instrument_id, trade_date, open, high, low, close, volume
            FROM ohlcv_daily
            WHERE trade_date BETWEEN %s AND %s
            ORDER BY instrument_id, trade_date
            """,
            (start, run_date),
        )
        rows = cur.fetchall()

    by_instrument: dict[int, list[tuple]] = {}
    for instrument_id, trade_date, o, h, l, c, v in rows:
        by_instrument.setdefault(instrument_id, []).append((trade_date, o, h, l, c, v))

    result = {}
    for instrument_id, recs in by_instrument.items():
        if recs[-1][0] != run_date:
            continue  # no data on run_date itself (e.g. newly delisted) — skip
        df = pd.DataFrame(recs, columns=["trade_date", "open", "high", "low", "close", "volume"])
        df = df.set_index("trade_date")
        result[instrument_id] = df.astype(float)

    return result
