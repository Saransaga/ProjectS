from psycopg2.extras import execute_values

from .upsert import _dec, _int

_CASH_FLOW_COLUMNS = ["category", "buy_value_cr", "sell_value_cr", "net_value_cr", "source"]
_PARTICIPANT_OI_COLUMNS = [
    "client_type",
    "fut_index_long", "fut_index_short", "fut_stock_long", "fut_stock_short",
    "opt_index_call_long", "opt_index_put_long", "opt_index_call_short", "opt_index_put_short",
    "opt_stock_call_long", "opt_stock_put_long", "opt_stock_call_short", "opt_stock_put_short",
    "total_long_contracts", "total_short_contracts",
    "source",
]
_DEAL_COLUMNS = ["deal_date", "deal_type", "client_name", "buy_sell", "quantity", "trade_price", "source"]

_NON_NUMERIC = {"category", "client_type", "source", "deal_date", "deal_type", "client_name", "buy_sell"}


def _convert(column: str, value):
    if column in _NON_NUMERIC:
        return value
    if column == "trade_price":
        return _dec(value)
    return _int(value)


def bulk_upsert_fii_dii_cash_flows(conn, rows: list[dict]) -> int:
    """Each row: flow_date, plus the keys in _CASH_FLOW_COLUMNS (see
    jobs/fii_dii_flows.py)."""
    if not rows:
        return 0
    values = [(r["flow_date"],) + tuple(_convert(c, r.get(c)) for c in _CASH_FLOW_COLUMNS) for r in rows]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _CASH_FLOW_COLUMNS if c != "category")
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO fii_dii_cash_flows (flow_date, {", ".join(_CASH_FLOW_COLUMNS)})
            VALUES %s
            ON CONFLICT (flow_date, category) DO UPDATE SET {set_clause}
            """,
            values,
        )
    return len(values)


def bulk_upsert_fno_participant_oi(conn, rows: list[dict]) -> int:
    """Each row: oi_date, plus the keys in _PARTICIPANT_OI_COLUMNS (see
    jobs/fii_dii_flows.py / nse_client.fetch_participant_oi)."""
    if not rows:
        return 0
    values = [(r["oi_date"],) + tuple(_convert(c, r.get(c)) for c in _PARTICIPANT_OI_COLUMNS) for r in rows]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _PARTICIPANT_OI_COLUMNS if c != "client_type")
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO fno_participant_oi (oi_date, {", ".join(_PARTICIPANT_OI_COLUMNS)})
            VALUES %s
            ON CONFLICT (oi_date, client_type) DO UPDATE SET {set_clause}
            """,
            values,
        )
    return len(values)


def bulk_upsert_bulk_block_deals(conn, rows: list[dict]) -> int:
    """Each row: instrument_id, plus the keys in _DEAL_COLUMNS (see
    jobs/bulk_block_deals.py). The UNIQUE constraint's columns already cover
    every field this table has other than deal_id/created_at, so a conflict
    means "this exact deal was already ingested on an earlier poll this
    day" — nothing to update, DO NOTHING."""
    if not rows:
        return 0
    values = [(r["instrument_id"],) + tuple(_convert(c, r.get(c)) for c in _DEAL_COLUMNS) for r in rows]
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO bulk_block_deals (instrument_id, {", ".join(_DEAL_COLUMNS)})
            VALUES %s
            ON CONFLICT (instrument_id, deal_date, deal_type, client_name, buy_sell, quantity, trade_price)
            DO NOTHING
            """,
            values,
        )
    return len(values)


def update_delivery_volume(conn, rows: list[dict]) -> int:
    """Each row: instrument_id, trade_date, delivery_qty, delivery_pct. An
    UPDATE against ohlcv_daily's existing PK, not an INSERT — see
    jobs/deliverable_volume.py. A row with no matching (instrument_id,
    trade_date) in ohlcv_daily yet is silently a no-op (e.g. this ran before
    EquityEodJob for some reason), not an error."""
    if not rows:
        return 0
    values = [(r["instrument_id"], r["trade_date"], _int(r["delivery_qty"]), _dec(r["delivery_pct"])) for r in rows]
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            UPDATE ohlcv_daily AS o SET
                delivery_qty = v.delivery_qty,
                delivery_pct = v.delivery_pct
            FROM (VALUES %s) AS v (instrument_id, trade_date, delivery_qty, delivery_pct)
            WHERE o.instrument_id = v.instrument_id AND o.trade_date = v.trade_date
            """,
            values,
        )
        return cur.rowcount
