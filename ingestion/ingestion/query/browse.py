"""Bulk/paginated reads for the product dashboard's FastAPI backend — kept
separate from query/snapshot.py, whose own docstring scopes it to
single-instrument/low-volume Telegram-bot lookups. Every function here is a
plain (conn, ...) -> ... call, no framework dependency, so the API layer can
unit-test/reuse them the same way jobs/recommendation_engine.py reuses
query/snapshot.py's price_levels().
"""

from datetime import date, timedelta

_HORIZONS = ("short", "long")


def _latest_recommendation_date(conn) -> date | None:
    with conn.cursor() as cur:
        cur.execute("SELECT max(as_of_date) FROM stock_recommendations")
        row = cur.fetchone()
    return row[0] if row else None


def get_instrument(conn, instrument_id: int) -> dict | None:
    """Symbol/name/sector for one instrument — the API's recommendation
    detail endpoint needs this alongside query/snapshot.py's per-instrument
    functions, none of which carry the instrument's own identity fields."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT instrument_id, symbol, name, sector FROM instruments WHERE instrument_id = %s",
            (instrument_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    instrument_id, symbol, name, sector = row
    return {"instrument_id": instrument_id, "symbol": symbol, "name": name, "sector": sector}


def list_recommendations(
    conn,
    as_of_date: date | None = None,
    horizon: str = "short",
    actions: list[str] | None = None,
    limit: int = 50,
    offset: int = 0,
    sort: str = "score_desc",
) -> tuple[list[dict], int, date | None]:
    """Paginated list of every instrument's latest recommendation as of
    `as_of_date` (defaults to the most recent date with any recommendations
    at all — same "find today's" pattern as query/snapshot.py's
    latest_recommendation_date). `actions` filters to a subset of the 5-level
    vocabulary; `sort` is one of "score_desc"/"score_asc"/"symbol"."""
    if horizon not in _HORIZONS:
        raise ValueError(f"horizon must be one of {_HORIZONS}, got {horizon!r}")
    if as_of_date is None:
        as_of_date = _latest_recommendation_date(conn)
    if as_of_date is None:
        return [], 0, None

    score_col = f"{horizon}_term_score"
    action_col = f"{horizon}_term_action"
    rationale_col = f"{horizon}_term_rationale"

    order = {
        "score_desc": f"r.{score_col} DESC NULLS LAST",
        "score_asc": f"r.{score_col} ASC NULLS LAST",
        "symbol": "i.symbol ASC",
    }.get(sort, f"r.{score_col} DESC NULLS LAST")

    where = ["r.as_of_date = %s"]
    params: list = [as_of_date]
    if actions:
        where.append(f"r.{action_col} = ANY(%s)")
        params.append(actions)
    where_sql = " AND ".join(where)

    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM stock_recommendations r WHERE {where_sql}", params)
        total = cur.fetchone()[0]

        cur.execute(
            f"""
            SELECT r.instrument_id, i.symbol, i.name, i.sector,
                   r.{score_col}, r.{action_col}, r.{rationale_col}
            FROM stock_recommendations r
            JOIN instruments i ON i.instrument_id = r.instrument_id
            WHERE {where_sql}
            ORDER BY {order}
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = [
            {
                "instrument_id": instrument_id, "symbol": symbol, "name": name, "sector": sector,
                "score": float(score) if score is not None else None,
                "action": action, "rationale": rationale,
            }
            for instrument_id, symbol, name, sector, score, action, rationale in cur.fetchall()
        ]
    return rows, total, as_of_date


def list_outcomes(
    conn,
    action: str | None = None,
    status: str | None = None,
    instrument_id: int | None = None,
    horizon: str = "short",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Paginated recommendation_outcomes rows, newest call first, optionally
    filtered to one action/status/instrument. `latest_close` is joined in per
    row (each row's own instrument's most recent ohlcv_daily close) so the API
    can compute "how far along toward target" without a second round trip per
    row."""
    where = ["o.horizon = %s"]
    params: list = [horizon]
    if action:
        where.append("o.action = %s")
        params.append(action)
    if status:
        where.append("o.status = %s")
        params.append(status)
    if instrument_id is not None:
        where.append("o.instrument_id = %s")
        params.append(instrument_id)
    where_sql = " AND ".join(where)

    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM recommendation_outcomes o WHERE {where_sql}", params)
        total = cur.fetchone()[0]

        cur.execute(
            f"""
            SELECT o.instrument_id, i.symbol, i.name, o.as_of_date, o.action,
                   o.dominant_component, o.entry_close, o.target_price, o.target_is_projected,
                   o.stop_price, o.stop_is_projected, o.status, o.trading_days_elapsed,
                   o.resolved_date, o.resolved_close,
                   (SELECT close FROM ohlcv_daily d WHERE d.instrument_id = o.instrument_id
                    ORDER BY d.trade_date DESC LIMIT 1) AS latest_close
            FROM recommendation_outcomes o
            JOIN instruments i ON i.instrument_id = o.instrument_id
            WHERE {where_sql}
            ORDER BY o.as_of_date DESC, o.instrument_id
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        columns = [
            "instrument_id", "symbol", "name", "as_of_date", "action", "dominant_component",
            "entry_close", "target_price", "target_is_projected", "stop_price", "stop_is_projected",
            "status", "trading_days_elapsed", "resolved_date", "resolved_close", "latest_close",
        ]
        rows = []
        for record in cur.fetchall():
            row = dict(zip(columns, record))
            for money_col in ("entry_close", "target_price", "stop_price", "resolved_close", "latest_close"):
                if row[money_col] is not None:
                    row[money_col] = float(row[money_col])
            rows.append(row)
    return rows, total


def outcome_summary(conn, horizon: str = "short", actions: list[str] | None = None) -> dict:
    """Win rate (HIT_TARGET / (HIT_TARGET + HIT_STOP), EXPIRED/OPEN excluded
    from the denominator since neither is a resolved win or loss), average
    trading days to resolution, and counts by status — the headline numbers
    for the Performance view."""
    where = ["horizon = %s"]
    params: list = [horizon]
    if actions:
        where.append("action = ANY(%s)")
        params.append(actions)
    where_sql = " AND ".join(where)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT status, count(*), avg(trading_days_elapsed) FILTER (WHERE status IN ('HIT_TARGET', 'HIT_STOP'))
            FROM recommendation_outcomes
            WHERE {where_sql}
            GROUP BY status
            """,
            params,
        )
        counts = {"OPEN": 0, "HIT_TARGET": 0, "HIT_STOP": 0, "EXPIRED": 0}
        avg_days_to_resolution = None
        for status, count, avg_days in cur.fetchall():
            counts[status] = count
            if avg_days is not None:
                avg_days_to_resolution = float(avg_days)

    resolved = counts["HIT_TARGET"] + counts["HIT_STOP"]
    win_rate = (counts["HIT_TARGET"] / resolved) if resolved else None
    return {
        "counts": counts,
        "total": sum(counts.values()),
        "win_rate": win_rate,
        "avg_days_to_resolution": avg_days_to_resolution,
    }


def outcome_breakdown_by_action(conn, horizon: str = "short") -> list[dict]:
    """Win rate per action bucket (STRONG_BUY vs BUY vs SELL vs STRONG_SELL) —
    lets the UI show whether stronger conviction calls actually perform
    better, not just an aggregate number."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT action, status, count(*)
            FROM recommendation_outcomes
            WHERE horizon = %s
            GROUP BY action, status
            """,
            (horizon,),
        )
        by_action: dict[str, dict[str, int]] = {}
        for action, status, count in cur.fetchall():
            by_action.setdefault(action, {"OPEN": 0, "HIT_TARGET": 0, "HIT_STOP": 0, "EXPIRED": 0})[status] = count

    results = []
    for action, counts in by_action.items():
        resolved = counts["HIT_TARGET"] + counts["HIT_STOP"]
        results.append({
            "action": action,
            "counts": counts,
            "total": sum(counts.values()),
            "win_rate": (counts["HIT_TARGET"] / resolved) if resolved else None,
        })
    return results


def outcome_breakdown_by_component(conn, horizon: str = "short") -> list[dict]:
    """Win rate grouped by which rationale component dominated the call at
    entry (recommendation_outcomes.dominant_component) — surfaces which
    signal types actually pay off vs. which just generate noisy calls."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT coalesce(dominant_component, 'unknown'), status, count(*)
            FROM recommendation_outcomes
            WHERE horizon = %s
            GROUP BY 1, status
            """,
            (horizon,),
        )
        by_component: dict[str, dict[str, int]] = {}
        for component, status, count in cur.fetchall():
            by_component.setdefault(component, {"OPEN": 0, "HIT_TARGET": 0, "HIT_STOP": 0, "EXPIRED": 0})[status] = count

    results = []
    for component, counts in by_component.items():
        resolved = counts["HIT_TARGET"] + counts["HIT_STOP"]
        results.append({
            "component": component,
            "counts": counts,
            "total": sum(counts.values()),
            "win_rate": (counts["HIT_TARGET"] / resolved) if resolved else None,
        })
    results.sort(key=lambda r: r["total"], reverse=True)
    return results


def source_health(conn, window_days: int = 30) -> dict:
    """news_items volume/credibility per source_type over a trailing window
    (the "least-used data sources" view), plus ingestion_log's rows_ingested
    trend per job over the same window (a job consistently landing 0-few rows
    vs. its peers)."""
    since = date.today() - timedelta(days=window_days)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT source_type, count(*), avg(source_credibility_weight),
                   max(published_at)
            FROM news_items
            WHERE fetched_at >= %s
            GROUP BY source_type
            ORDER BY count(*) DESC
            """,
            (since,),
        )
        sources = [
            {
                "source_type": source_type,
                "item_count": count,
                "credibility_weight": float(credibility) if credibility is not None else None,
                "latest_published_at": latest,
            }
            for source_type, count, credibility, latest in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT job_name, count(*) FILTER (WHERE status = 'SUCCESS'),
                   sum(rows_ingested) FILTER (WHERE status = 'SUCCESS'),
                   avg(rows_ingested) FILTER (WHERE status = 'SUCCESS')
            FROM ingestion_log
            WHERE started_at >= %s
            GROUP BY job_name
            ORDER BY avg(rows_ingested) FILTER (WHERE status = 'SUCCESS') ASC NULLS LAST
            """,
            (since,),
        )
        jobs = [
            {
                "job_name": job_name,
                "successful_runs": success_count,
                "total_rows_ingested": int(total_rows) if total_rows is not None else 0,
                "avg_rows_per_run": float(avg_rows) if avg_rows is not None else None,
            }
            for job_name, success_count, total_rows, avg_rows in cur.fetchall()
        ]

    return {"window_days": window_days, "news_sources": sources, "jobs": jobs}


def job_latest_runs(conn) -> list[dict]:
    """Most recent ingestion_log row per job_name (same `DISTINCT ON
    (job_name) ... ORDER BY job_name, run_date DESC` query
    ingestion/dashboard.py's Overview tab already uses), plus
    `last_success_finished_at` alongside it. The two are deliberately
    different things: the latest *attempt* can be a FAILED run with a very
    recent finished_at — job_cadence.py's freshness judgment must use the
    latest *successful* run's timestamp, or a job that fails on every tick
    would misleadingly read as FRESH forever."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT l.job_name, l.run_date, l.status, l.rows_ingested, l.error,
                   l.started_at, l.finished_at, s.last_success_finished_at
            FROM (
                SELECT DISTINCT ON (job_name)
                    job_name, run_date, status, rows_ingested, error, started_at, finished_at
                FROM ingestion_log
                ORDER BY job_name, run_date DESC
            ) l
            LEFT JOIN (
                SELECT job_name, max(finished_at) AS last_success_finished_at
                FROM ingestion_log
                WHERE status = 'SUCCESS'
                GROUP BY job_name
            ) s ON s.job_name = l.job_name
            """
        )
        columns = [
            "job_name", "run_date", "status", "rows_ingested", "error",
            "started_at", "finished_at", "last_success_finished_at",
        ]
        return [dict(zip(columns, record)) for record in cur.fetchall()]
