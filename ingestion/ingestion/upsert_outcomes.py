from psycopg2.extras import execute_values

from .upsert import _dec

_INSERT_COLUMNS = [
    "instrument_id", "as_of_date", "horizon", "action", "dominant_component",
    "entry_close", "target_price", "target_is_projected", "stop_price", "stop_is_projected",
    "atr_14_at_entry", "last_checked_date",
]
_NON_NUMERIC = {
    "instrument_id", "as_of_date", "horizon", "action", "dominant_component",
    "target_is_projected", "stop_is_projected", "last_checked_date",
}


def _convert(column: str, value):
    return value if column in _NON_NUMERIC else _dec(value)


def bulk_insert_recommendation_outcomes(conn, rows: list[dict]) -> int:
    """Each row: the columns in _INSERT_COLUMNS (see
    jobs/recommendation_outcomes.py::RecommendationOutcomesJob.fetch). A new
    call is opened once per (instrument_id, as_of_date, horizon) and never
    re-opened by a later idempotent rerun — ON CONFLICT DO NOTHING, unlike
    stock_recommendations' DO UPDATE, since a call's entry snapshot must never
    be silently overwritten by a later recompute."""
    if not rows:
        return 0
    values = [tuple(_convert(c, r.get(c)) for c in _INSERT_COLUMNS) for r in rows]
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO recommendation_outcomes ({", ".join(_INSERT_COLUMNS)})
            VALUES %s
            ON CONFLICT (instrument_id, as_of_date, horizon) DO NOTHING
            """,
            values,
        )
    return len(values)


def bulk_update_resolved_outcomes(conn, rows: list[dict]) -> int:
    """Each row: instrument_id, as_of_date, horizon (the PK) plus status,
    trading_days_elapsed, resolved_date, resolved_close, last_checked_date —
    the fields jobs/recommendation_outcomes.py's day-by-day walk updates on
    every check, whether or not the call actually resolved this run."""
    if not rows:
        return 0
    values = [
        (
            r["instrument_id"], r["as_of_date"], r["horizon"],
            r["status"], r["trading_days_elapsed"], r["resolved_date"], _dec(r["resolved_close"]),
            r["last_checked_date"],
        )
        for r in rows
    ]
    with conn.cursor() as cur:
        # Explicit per-column casts (via `template`): resolved_date/resolved_close
        # are NULL for a still-OPEN row, and Postgres can't infer a bare NULL
        # literal's type from a multi-row VALUES list on its own.
        execute_values(
            cur,
            """
            UPDATE recommendation_outcomes AS o SET
                status = v.status,
                trading_days_elapsed = v.trading_days_elapsed,
                resolved_date = v.resolved_date,
                resolved_close = v.resolved_close,
                last_checked_date = v.last_checked_date,
                updated_at = now()
            FROM (VALUES %s) AS v (
                instrument_id, as_of_date, horizon, status, trading_days_elapsed,
                resolved_date, resolved_close, last_checked_date
            )
            WHERE o.instrument_id = v.instrument_id
              AND o.as_of_date = v.as_of_date
              AND o.horizon = v.horizon
            """,
            values,
            template="(%s::bigint, %s::date, %s::text, %s::text, %s::integer, %s::date, %s::numeric, %s::date)",
        )
    return len(values)
