from datetime import date
from decimal import Decimal, InvalidOperation

from psycopg2.extras import execute_values


def _dec(v) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return None


def _int(v) -> int | None:
    d = _dec(v)
    return int(d) if d is not None else None


def upsert_instrument(
    conn,
    symbol: str,
    exchange: str,
    instrument_type: str,
    trade_date: date,
    series: str | None = None,
    name: str | None = None,
    isin: str | None = None,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO instruments
                (symbol, exchange, instrument_type, series, name, isin,
                 first_seen_date, last_seen_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (exchange, symbol, instrument_type) DO UPDATE SET
                series = EXCLUDED.series,
                name = EXCLUDED.name,
                isin = COALESCE(EXCLUDED.isin, instruments.isin),
                last_seen_date = GREATEST(instruments.last_seen_date, EXCLUDED.last_seen_date),
                updated_at = now()
            RETURNING instrument_id
            """,
            (symbol, exchange, instrument_type, series, name, isin, trade_date, trade_date),
        )
        return cur.fetchone()[0]


def bulk_upsert_ohlcv(conn, rows: list[dict]) -> int:
    """Each row: instrument_id, trade_date, open, high, low, close, prev_close,
    volume, turnover, trades, source (delivery_qty/delivery_pct not populated
    by this pass's sources, left NULL)."""
    if not rows:
        return 0

    values = [
        (
            r["instrument_id"],
            r["trade_date"],
            _dec(r["open"]),
            _dec(r["high"]),
            _dec(r["low"]),
            _dec(r["close"]),
            _dec(r.get("prev_close")),
            _int(r.get("volume")),
            _dec(r.get("turnover")),
            _int(r.get("trades")),
            r.get("source", "NSE_BHAVCOPY"),
        )
        for r in rows
    ]

    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO ohlcv_daily
                (instrument_id, trade_date, open, high, low, close, prev_close,
                 volume, turnover, trades, source)
            VALUES %s
            ON CONFLICT (instrument_id, trade_date) DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                prev_close = EXCLUDED.prev_close,
                volume = EXCLUDED.volume,
                turnover = EXCLUDED.turnover,
                trades = EXCLUDED.trades,
                source = EXCLUDED.source
            """,
            values,
        )
    return len(values)
