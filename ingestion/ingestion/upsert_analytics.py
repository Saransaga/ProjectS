from datetime import date

from psycopg2.extras import Json, execute_values

from .upsert import _dec, _int

# obv/volume_sma_20 are BIGINT columns; everything else is NUMERIC or the
# supertrend_direction TEXT enum.
_BIGINT_COLUMNS = {"obv", "volume_sma_20"}


def _convert(column: str, value):
    if column == "supertrend_direction":
        return value
    if column in _BIGINT_COLUMNS:
        return _int(value)
    return _dec(value)


_INDICATOR_COLUMNS = [
    "ema_9", "ema_21", "ema_50", "ema_100", "ema_200",
    "sma_20", "sma_50", "sma_200",
    "adx_14", "supertrend_7_3", "supertrend_direction",
    "ichimoku_tenkan", "ichimoku_kijun", "ichimoku_senkou_a", "ichimoku_senkou_b", "ichimoku_chikou",
    "rsi_14", "macd", "macd_signal", "macd_hist", "stoch_k", "stoch_d", "roc_12", "cci_14",
    "obv", "vwap_20", "volume_sma_20", "mfi_14",
    "bb_upper", "bb_mid", "bb_lower", "atr_14", "keltner_upper", "keltner_mid", "keltner_lower",
]

_CANDLESTICK_COLUMNS = [
    "cdl_doji", "cdl_engulfing", "cdl_hammer", "cdl_shooting_star",
    "cdl_morning_star", "cdl_evening_star", "cdl_harami",
    "cdl_three_white_soldiers", "cdl_three_black_crows",
]


def bulk_upsert_technical_indicators(conn, rows: list[dict]) -> int:
    """Each row: instrument_id, trade_date, plus the keys in _INDICATOR_COLUMNS
    (see analytics.indicators.compute_indicators)."""
    if not rows:
        return 0

    values = [
        (r["instrument_id"], r["trade_date"]) + tuple(_convert(c, r.get(c)) for c in _INDICATOR_COLUMNS)
        for r in rows
    ]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _INDICATOR_COLUMNS)

    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO technical_indicators_daily
                (instrument_id, trade_date, {", ".join(_INDICATOR_COLUMNS)})
            VALUES %s
            ON CONFLICT (instrument_id, trade_date) DO UPDATE SET
                {set_clause},
                computed_at = now()
            """,
            values,
        )
    return len(values)


def bulk_upsert_candlestick_patterns(conn, rows: list[dict]) -> int:
    """Each row: instrument_id, trade_date, plus the keys in _CANDLESTICK_COLUMNS
    (see analytics.candlestick.compute_candlestick_patterns)."""
    if not rows:
        return 0

    values = [
        (r["instrument_id"], r["trade_date"]) + tuple(_int(r.get(c)) for c in _CANDLESTICK_COLUMNS)
        for r in rows
    ]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _CANDLESTICK_COLUMNS)

    with conn.cursor() as cur:
        execute_values(
            cur,
            f"""
            INSERT INTO candlestick_patterns_daily
                (instrument_id, trade_date, {", ".join(_CANDLESTICK_COLUMNS)})
            VALUES %s
            ON CONFLICT (instrument_id, trade_date) DO UPDATE SET
                {set_clause},
                computed_at = now()
            """,
            values,
        )
    return len(values)


def replace_signal_events(conn, event_date: date, instrument_ids: list[int], rows: list[dict]) -> int:
    """Events, like support/resistance levels, are re-detected from scratch
    each run rather than accumulated — a condition that no longer holds on a
    re-run (e.g. after a data correction) must not leave a stale row behind.
    Replaces every event for event_date across instrument_ids with the freshly
    detected set."""
    with conn.cursor() as cur:
        if instrument_ids:
            cur.execute(
                "DELETE FROM signal_events WHERE event_date = %s AND instrument_id = ANY(%s)",
                (event_date, instrument_ids),
            )
        if not rows:
            return 0
        values = [(r["instrument_id"], r["event_date"], r["event_type"], Json(r["details"])) for r in rows]
        execute_values(
            cur,
            """
            INSERT INTO signal_events (instrument_id, event_date, event_type, details)
            VALUES %s
            """,
            values,
        )
    return len(rows)


def replace_support_resistance_levels(conn, instrument_id: int, computed_date: date, levels: list[dict]) -> int:
    """Levels are a fresh clustering computed from scratch each run, not an
    append-only history — replace the instrument's prior set outright."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM support_resistance_levels WHERE instrument_id = %s", (instrument_id,))
        if levels:
            execute_values(
                cur,
                """
                INSERT INTO support_resistance_levels
                    (instrument_id, level_type, price_level, strength,
                     first_touch_date, last_touch_date, computed_date)
                VALUES %s
                """,
                [
                    (
                        instrument_id,
                        lv["level_type"],
                        _dec(lv["price_level"]),
                        lv["strength"],
                        lv["first_touch_date"],
                        lv["last_touch_date"],
                        computed_date,
                    )
                    for lv in levels
                ],
            )
    return len(levels)
