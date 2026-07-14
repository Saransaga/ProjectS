from psycopg2.extras import execute_values

from .upsert import _dec, _int

_RS_COLUMNS = [
    "return_1w", "return_1m", "return_3m", "return_6m", "return_1y",
    "relative_return_1w", "relative_return_1m", "relative_return_3m", "relative_return_6m", "relative_return_1y",
    "rs_rating",
]


def _convert(column: str, value):
    return _int(value) if column == "rs_rating" else _dec(value)


def bulk_upsert_relative_strength(conn, rows: list[dict]) -> int:
    """Each row: instrument_id, trade_date, plus the keys in _RS_COLUMNS
    (see momentum/relative_strength.py)."""
    if not rows:
        return 0
    values = [
        (r["instrument_id"], r["trade_date"]) + tuple(_convert(c, r.get(c)) for c in _RS_COLUMNS)
        for r in rows
    ]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _RS_COLUMNS)
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO relative_strength (instrument_id, trade_date, {", ".join(_RS_COLUMNS)})
            VALUES %s
            ON CONFLICT (instrument_id, trade_date) DO UPDATE SET {set_clause}, computed_at = now()
            """,
            values,
        )
    return len(values)
