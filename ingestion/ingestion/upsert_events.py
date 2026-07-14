from psycopg2.extras import execute_values

from .upsert import _dec, _int

_CALENDAR_COLUMNS = ["event_date", "event_type", "purpose", "description", "consensus_eps_estimate", "source"]
_IPO_LISTING_COLUMNS = [
    "company_name", "instrument_id",
    "issue_price_low", "issue_price_high", "issue_size_shares",
    "issue_end_date", "status",
    "listing_date", "listing_open", "listing_high", "listing_low", "listing_close", "listing_volume",
    "source",
]

_NON_NUMERIC = {
    "event_date", "event_type", "purpose", "description", "source",
    "company_name", "status", "issue_start_date", "issue_end_date", "listing_date",
}
_BIGINT_COLUMNS = {"instrument_id", "issue_size_shares", "listing_volume"}


def _convert(column: str, value):
    if column in _NON_NUMERIC:
        return value
    if column in _BIGINT_COLUMNS:
        return _int(value)
    return _dec(value)


def bulk_upsert_corporate_calendar(conn, rows: list[dict]) -> int:
    """Each row: instrument_id, plus the keys in _CALENDAR_COLUMNS (see
    events/classify.py). A rescheduled board meeting lands as a new row under
    its new event_date rather than overwriting the old one — the original
    schedule stays visible as calendar history, same as corporate_actions
    never overwriting a prior action.

    NSE's board-meetings feed genuinely repeats the same (symbol, date,
    purpose) intimation more than once in a single response (confirmed: not
    a bug in the fetch) — collapse to one row per conflict target here,
    since Postgres' ON CONFLICT DO UPDATE can't touch the same row twice in
    one execute_values batch."""
    if not rows:
        return 0
    deduped = {(r["instrument_id"], r["event_date"], r["purpose"]): r for r in rows}
    values = [
        (r["instrument_id"],) + tuple(_convert(c, r.get(c)) for c in _CALENDAR_COLUMNS)
        for r in deduped.values()
    ]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _CALENDAR_COLUMNS if c not in ("event_date", "purpose"))
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO corporate_calendar (instrument_id, {", ".join(_CALENDAR_COLUMNS)})
            VALUES %s
            ON CONFLICT (instrument_id, event_date, purpose) DO UPDATE SET {set_clause}
            """,
            values,
        )
    return len(values)


def bulk_upsert_index_rebalancing_schedule(conn, rows: list[dict]) -> int:
    """Each row: index_name, rebalance_frequency, source (see
    jobs/index_rebalancing.py). Reference table, keyed on index_name alone —
    no per-run history, each upsert just refreshes the current cadence."""
    if not rows:
        return 0
    values = [(r["index_name"], r["rebalance_frequency"], r["source"]) for r in rows]
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO index_rebalancing_schedule (index_name, rebalance_frequency, source, updated_at)
            VALUES %s
            ON CONFLICT (index_name) DO UPDATE SET
                rebalance_frequency = EXCLUDED.rebalance_frequency,
                source = EXCLUDED.source,
                updated_at = now()
            """,
            values,
            template="(%s, %s, %s, now())",
        )
    return len(values)


def upsert_macro_event(conn, event_date, category: str, description: str, source: str = "MANUAL") -> None:
    """Manual entry point for macro_events — see init.sql's Domain 7 section
    for why there's no automated job (RBI/MOSPI publish no scrapeable
    calendar), wired up as `cli.py macro-event add`."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO macro_events (event_date, category, description, source)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (event_date, category) DO UPDATE SET
                description = EXCLUDED.description,
                source = EXCLUDED.source
            """,
            (event_date, category, description, source),
        )


def bulk_upsert_ipo_listings(conn, rows: list[dict]) -> int:
    """Each row: symbol, issue_start_date, plus the keys in
    _IPO_LISTING_COLUMNS (see jobs/ipo_listings.py). Re-upserting the same
    (symbol, issue_start_date) lets a later run fill in instrument_id/
    listing_* once IpoListingsJob resolves the first ohlcv_daily row after
    issue_end_date — status flips ACTIVE -> CLOSED -> LISTED across runs.

    A symbol can appear in both IpoListingsJob's fresh-feed batch and its
    same-run backfill batch (still on the live NSE feed as CLOSED the same
    day its listing gets resolved) — same one-row-per-conflict-target
    constraint as bulk_upsert_corporate_calendar. The backfill row always
    comes later in the list (fetch() extends with it after the live-feed
    rows), so keeping the last occurrence per key means the backfilled
    LISTED state wins over the stale CLOSED one."""
    if not rows:
        return 0
    deduped = {(r["symbol"], r["issue_start_date"]): r for r in rows}
    values = [
        (r["symbol"], r["issue_start_date"]) + tuple(_convert(c, r.get(c)) for c in _IPO_LISTING_COLUMNS)
        for r in deduped.values()
    ]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _IPO_LISTING_COLUMNS)
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO ipo_listings (symbol, issue_start_date, {", ".join(_IPO_LISTING_COLUMNS)})
            VALUES %s
            ON CONFLICT (symbol, issue_start_date) DO UPDATE SET {set_clause}
            """,
            values,
        )
    return len(values)
