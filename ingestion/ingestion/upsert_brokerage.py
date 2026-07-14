from psycopg2.extras import execute_values

from .upsert import _dec

_BROKERAGE_CALL_COLUMNS = [
    "brokerage_name", "call_date", "raw_rating", "rating_bucket",
    "reco_price", "target_price", "report_url", "source",
]

_RATING_CHANGE_COLUMNS = [
    "brokerage_name", "event_date", "change_type",
    "previous_rating_bucket", "new_rating_bucket",
    "previous_target_price", "new_target_price", "source",
]

_NUMERIC_COLUMNS = {"reco_price", "target_price", "previous_target_price", "new_target_price"}


def _convert(column: str, value):
    return _dec(value) if column in _NUMERIC_COLUMNS else value


def bulk_upsert_brokerage_calls(conn, rows: list[dict]) -> int:
    """Each row: instrument_id, plus the keys in _BROKERAGE_CALL_COLUMNS (see
    jobs/brokerage_calls.py). Conflict target matches the table's own UNIQUE
    constraint: (instrument_id, brokerage_name, call_date, source) — a
    re-poll that finds the same brokerage's same-dated call again just
    refreshes the numbers/rating rather than duplicating the row."""
    if not rows:
        return 0
    values = [
        (r["instrument_id"],) + tuple(_convert(c, r.get(c)) for c in _BROKERAGE_CALL_COLUMNS)
        for r in rows
    ]
    set_clause = ", ".join(
        f"{c} = EXCLUDED.{c}"
        for c in _BROKERAGE_CALL_COLUMNS
        if c not in ("brokerage_name", "call_date", "source")
    )
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO brokerage_calls (instrument_id, {", ".join(_BROKERAGE_CALL_COLUMNS)})
            VALUES %s
            ON CONFLICT (instrument_id, brokerage_name, call_date, source) DO UPDATE SET {set_clause}
            """,
            values,
        )
    return len(values)


def bulk_upsert_rating_change_events(conn, rows: list[dict]) -> int:
    """Each row: instrument_id, plus the keys in _RATING_CHANGE_COLUMNS (see
    jobs/brokerage_calls.py's UPGRADE/DOWNGRADE/REITERATED/INITIATED
    detection). Conflict target (instrument_id, brokerage_name, event_date,
    source) is defense-in-depth against duplicate events on a re-run — the
    job itself is expected to only pass already-new call_dates here, this
    constraint just guards against it doing so twice."""
    if not rows:
        return 0
    values = [
        (r["instrument_id"],) + tuple(_convert(c, r.get(c)) for c in _RATING_CHANGE_COLUMNS)
        for r in rows
    ]
    set_clause = ", ".join(
        f"{c} = EXCLUDED.{c}"
        for c in _RATING_CHANGE_COLUMNS
        if c not in ("brokerage_name", "event_date", "source")
    )
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO rating_change_events (instrument_id, {", ".join(_RATING_CHANGE_COLUMNS)})
            VALUES %s
            ON CONFLICT (instrument_id, brokerage_name, event_date, source) DO UPDATE SET {set_clause}
            """,
            values,
        )
    return len(values)
