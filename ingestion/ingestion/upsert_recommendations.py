from psycopg2.extras import Json, execute_values

from .upsert import _dec

_COLUMNS = [
    "short_term_score", "short_term_action", "short_term_rationale",
    "long_term_score", "long_term_action", "long_term_rationale",
]

_JSON_COLUMNS = {"short_term_rationale", "long_term_rationale"}
_NON_NUMERIC = {"short_term_action", "long_term_action"} | _JSON_COLUMNS


def _convert(column: str, value):
    if column in _JSON_COLUMNS:
        return Json(value) if value is not None else None
    if column in _NON_NUMERIC:
        return value
    return _dec(value)


def bulk_upsert_stock_recommendations(conn, rows: list[dict]) -> int:
    """Each row: instrument_id, as_of_date, plus the keys in _COLUMNS (see
    recommendation/short_term.py's/long_term.py's score_short_term()/
    score_long_term() output, bucketized via recommendation/bucketize.py).
    Same column-list-driven execute_values upsert style as
    upsert_consensus.bulk_upsert_consensus_ratings."""
    if not rows:
        return 0
    values = [
        (r["instrument_id"], r["as_of_date"]) + tuple(_convert(c, r.get(c)) for c in _COLUMNS)
        for r in rows
    ]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _COLUMNS)
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO stock_recommendations (instrument_id, as_of_date, {", ".join(_COLUMNS)})
            VALUES %s
            ON CONFLICT (instrument_id, as_of_date) DO UPDATE SET {set_clause}, computed_at = now()
            """,
            values,
        )
    return len(values)
