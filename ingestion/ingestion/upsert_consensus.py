from psycopg2.extras import execute_values

from .upsert import _dec, _int

_CONSENSUS_COLUMNS = [
    "consensus_rating_bucket", "num_analysts", "avg_target_price", "implied_upside_pct",
    "tickertape_pct_buy", "tickertape_analyst_count",
]

_NON_NUMERIC = {"consensus_rating_bucket"}
_INT_COLUMNS = {"num_analysts", "tickertape_analyst_count"}


def _convert(column: str, value):
    if column in _NON_NUMERIC:
        return value
    if column in _INT_COLUMNS:
        return _int(value)
    return _dec(value)


def bulk_upsert_consensus_ratings(conn, rows: list[dict]) -> int:
    """Each row: instrument_id, as_of_date, plus the keys in
    _CONSENSUS_COLUMNS (see brokerage.consensus.compute_consensus_bucket and
    jobs/consensus_ratings.py). Same column-list-driven execute_values
    upsert style as upsert_fundamentals.bulk_upsert_fundamental_ratios, kept
    in a separate module so this file doesn't collide with the
    brokerage_calls ingestion work being built in parallel."""
    if not rows:
        return 0
    values = [
        (r["instrument_id"], r["as_of_date"]) + tuple(_convert(c, r.get(c)) for c in _CONSENSUS_COLUMNS)
        for r in rows
    ]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _CONSENSUS_COLUMNS)
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO consensus_ratings (instrument_id, as_of_date, {", ".join(_CONSENSUS_COLUMNS)})
            VALUES %s
            ON CONFLICT (instrument_id, as_of_date) DO UPDATE SET {set_clause}
            """,
            values,
        )
    return len(values)
