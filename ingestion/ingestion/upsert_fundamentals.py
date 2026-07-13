from psycopg2.extras import execute_values

from .upsert import _dec, _int

_CORPORATE_ACTION_COLUMNS = [
    "ex_date", "record_date", "action_type", "amount_per_share",
    "ratio_new", "ratio_old", "face_value_from", "face_value_to",
    "raw_subject", "series", "source",
]

_SHAREHOLDING_COLUMNS = [
    "promoter_pct", "public_pct", "fii_pct", "dii_pct", "pledged_promoter_pct",
    "submission_date", "xbrl_url", "source",
]

_FUNDAMENTALS_COLUMNS = [
    "financial_year", "reporting_quarter", "consolidated",
    "revenue", "pat", "eps_basic", "eps_diluted",
    "debt_to_equity", "interest_coverage_ratio", "ebitda_derived", "shares_outstanding",
    "broadcast_date", "xbrl_url", "source",
]

_RATIO_COLUMNS = [
    "pe_ratio", "ps_ratio", "dividend_yield", "payout_ratio",
    "pb_ratio", "ev_ebitda", "pfcf_ratio", "forward_pe", "roe", "roce", "roa",
]

_NON_NUMERIC = {
    "ex_date", "record_date", "action_type", "raw_subject", "series", "source",
    "submission_date", "xbrl_url", "financial_year", "reporting_quarter",
    "consolidated", "broadcast_date",
}
_BIGINT_COLUMNS = {"shares_outstanding"}


def _convert(column: str, value):
    if column in _NON_NUMERIC:
        return value
    if column in _BIGINT_COLUMNS:
        return _int(value)
    return _dec(value)


def bulk_upsert_corporate_actions(conn, rows: list[dict]) -> int:
    """Each row: instrument_id, plus the keys in _CORPORATE_ACTION_COLUMNS
    (see fundamentals.corporate_actions.classify)."""
    if not rows:
        return 0
    values = [
        (r["instrument_id"],) + tuple(_convert(c, r.get(c)) for c in _CORPORATE_ACTION_COLUMNS)
        for r in rows
    ]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _CORPORATE_ACTION_COLUMNS if c != "raw_subject")
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO corporate_actions (instrument_id, {", ".join(_CORPORATE_ACTION_COLUMNS)})
            VALUES %s
            ON CONFLICT (instrument_id, (COALESCE(ex_date, DATE '0001-01-01')), raw_subject) DO UPDATE SET {set_clause}
            """,
            values,
        )
    return len(values)


def bulk_upsert_shareholding_pattern(conn, rows: list[dict]) -> int:
    """Each row: instrument_id, period_end_date, plus the keys in
    _SHAREHOLDING_COLUMNS."""
    if not rows:
        return 0
    values = [
        (r["instrument_id"], r["period_end_date"]) + tuple(_convert(c, r.get(c)) for c in _SHAREHOLDING_COLUMNS)
        for r in rows
    ]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _SHAREHOLDING_COLUMNS)
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO shareholding_pattern
                (instrument_id, period_end_date, {", ".join(_SHAREHOLDING_COLUMNS)})
            VALUES %s
            ON CONFLICT (instrument_id, period_end_date) DO UPDATE SET {set_clause}
            """,
            values,
        )
    return len(values)


def bulk_upsert_fundamentals_quarterly(conn, rows: list[dict]) -> int:
    """Each row: instrument_id, period_end_date, plus the keys in
    _FUNDAMENTALS_COLUMNS (see fundamentals.xbrl_financial.parse_financial_results)."""
    if not rows:
        return 0
    values = [
        (r["instrument_id"], r["period_end_date"]) + tuple(_convert(c, r.get(c)) for c in _FUNDAMENTALS_COLUMNS)
        for r in rows
    ]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _FUNDAMENTALS_COLUMNS)
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO fundamentals_quarterly
                (instrument_id, period_end_date, {", ".join(_FUNDAMENTALS_COLUMNS)})
            VALUES %s
            ON CONFLICT (instrument_id, period_end_date, consolidated) DO UPDATE SET {set_clause}
            """,
            values,
        )
    return len(values)


def bulk_upsert_fundamental_ratios(conn, rows: list[dict]) -> int:
    """Each row: instrument_id, as_of_date, plus the keys in _RATIO_COLUMNS."""
    if not rows:
        return 0
    values = [
        (r["instrument_id"], r["as_of_date"]) + tuple(_convert(c, r.get(c)) for c in _RATIO_COLUMNS)
        for r in rows
    ]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _RATIO_COLUMNS)
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO fundamental_ratios (instrument_id, as_of_date, {", ".join(_RATIO_COLUMNS)})
            VALUES %s
            ON CONFLICT (instrument_id, as_of_date) DO UPDATE SET {set_clause}
            """,
            values,
        )
    return len(values)
