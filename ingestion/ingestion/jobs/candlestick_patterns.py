from datetime import date

from ..analytics.candlestick import compute_candlestick_patterns
from ..analytics.history import fetch_lookback_history
from ..db import get_conn
from ..upsert_analytics import bulk_upsert_candlestick_patterns
from .base import BaseJob


class CandlestickPatternsJob(BaseJob):
    """Reads ohlcv_daily and detects the 9 spec'd candlestick patterns on the
    latest bar via TA-Lib's CDL* functions."""

    job_name = "candlestick_patterns"

    def fetch(self, run_date: date) -> list[dict]:
        with get_conn() as conn:
            histories = fetch_lookback_history(conn, run_date)

        return [
            {"instrument_id": instrument_id, "trade_date": run_date, **compute_candlestick_patterns(df)}
            for instrument_id, df in histories.items()
        ]

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        with get_conn() as conn:
            return bulk_upsert_candlestick_patterns(conn, rows)
