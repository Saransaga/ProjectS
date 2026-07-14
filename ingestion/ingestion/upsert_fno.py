from psycopg2.extras import execute_values

from .upsert import _dec, _int

_BHAVCOPY_COLUMNS = [
    "underlying_symbol", "underlying_type", "instrument_id", "contract_type", "expiry_date",
    "option_type", "strike_price",
    "open_price", "high_price", "low_price", "close_price", "settle_price", "prev_close",
    "underlying_price", "open_interest", "change_in_oi", "volume", "turnover", "trades",
    "lot_size", "source",
]
_SIGNAL_COLUMNS = ["pcr_oi", "pcr_volume", "max_pain_strike"]
_BUILDUP_COLUMNS = ["price_change_pct", "oi_change_pct", "buildup_type"]
_ROLLOVER_COLUMNS = ["near_expiry", "next_expiry", "near_oi", "next_oi", "rollover_pct"]

_NON_NUMERIC_BHAVCOPY = {
    "underlying_symbol", "underlying_type", "instrument_id", "contract_type", "expiry_date",
    "option_type", "source",
}
_BIGINT_BHAVCOPY = {"open_interest", "change_in_oi", "volume", "trades", "lot_size"}


def _convert_bhavcopy(column: str, value):
    if column in _NON_NUMERIC_BHAVCOPY:
        return value
    if column in _BIGINT_BHAVCOPY:
        return _int(value)
    return _dec(value)


def bulk_upsert_fno_bhavcopy(conn, rows: list[dict]) -> int:
    """Each row: trade_date, plus the keys in _BHAVCOPY_COLUMNS (see
    jobs/fno_bhavcopy.py). Conflict target is the COALESCE-based dedup index
    (option_type/strike_price are NULL for futures rows) — same technique as
    Domain 3's corporate_actions dedup index."""
    if not rows:
        return 0
    values = [(r["trade_date"],) + tuple(_convert_bhavcopy(c, r.get(c)) for c in _BHAVCOPY_COLUMNS) for r in rows]
    set_clause = ", ".join(
        f"{c} = EXCLUDED.{c}"
        for c in _BHAVCOPY_COLUMNS
        if c not in ("underlying_symbol", "contract_type", "expiry_date", "option_type", "strike_price")
    )
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO fno_bhavcopy_daily (trade_date, {", ".join(_BHAVCOPY_COLUMNS)})
            VALUES %s
            ON CONFLICT (underlying_symbol, contract_type, expiry_date,
                         (COALESCE(option_type, '')), (COALESCE(strike_price, -1)), trade_date)
            DO UPDATE SET {set_clause}
            """,
            values,
        )
    return len(values)


def bulk_upsert_fno_signals(conn, rows: list[dict]) -> int:
    """Each row: underlying_symbol, expiry_date, trade_date, plus the keys
    in _SIGNAL_COLUMNS (see momentum/pcr.py)."""
    if not rows:
        return 0
    values = [
        (r["underlying_symbol"], r["expiry_date"], r["trade_date"]) + tuple(_dec(r.get(c)) for c in _SIGNAL_COLUMNS)
        for r in rows
    ]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _SIGNAL_COLUMNS)
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO fno_signals (underlying_symbol, expiry_date, trade_date, {", ".join(_SIGNAL_COLUMNS)})
            VALUES %s
            ON CONFLICT (underlying_symbol, expiry_date, trade_date) DO UPDATE SET {set_clause}, computed_at = now()
            """,
            values,
        )
    return len(values)


def bulk_upsert_fno_oi_buildup(conn, rows: list[dict]) -> int:
    """Each row: underlying_symbol, expiry_date, trade_date, plus the keys
    in _BUILDUP_COLUMNS (see momentum/oi_buildup.py)."""
    if not rows:
        return 0
    values = [
        (r["underlying_symbol"], r["expiry_date"], r["trade_date"], _dec(r["price_change_pct"]),
         _dec(r["oi_change_pct"]), r["buildup_type"])
        for r in rows
    ]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _BUILDUP_COLUMNS)
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO fno_oi_buildup (underlying_symbol, expiry_date, trade_date, {", ".join(_BUILDUP_COLUMNS)})
            VALUES %s
            ON CONFLICT (underlying_symbol, expiry_date, trade_date) DO UPDATE SET {set_clause}, computed_at = now()
            """,
            values,
        )
    return len(values)


def bulk_upsert_fno_rollover(conn, rows: list[dict]) -> int:
    """Each row: underlying_symbol, trade_date, plus the keys in
    _ROLLOVER_COLUMNS (see momentum/rollover.py)."""
    if not rows:
        return 0
    values = [
        (
            r["underlying_symbol"], r["trade_date"], r["near_expiry"], r["next_expiry"],
            _int(r["near_oi"]), _int(r["next_oi"]), _dec(r["rollover_pct"]),
        )
        for r in rows
    ]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _ROLLOVER_COLUMNS)
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO fno_rollover (underlying_symbol, trade_date, {", ".join(_ROLLOVER_COLUMNS)})
            VALUES %s
            ON CONFLICT (underlying_symbol, trade_date) DO UPDATE SET {set_clause}, computed_at = now()
            """,
            values,
        )
    return len(values)
