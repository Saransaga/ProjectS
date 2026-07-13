from datetime import date

from ..analytics.history import fetch_lookback_history
from ..analytics.indicators import compute_indicators
from ..db import get_conn
from ..upsert_analytics import bulk_upsert_technical_indicators
from .base import BaseJob


class TechnicalIndicatorsJob(BaseJob):
    """Reads ohlcv_daily (not an external source) and computes trend/momentum/
    volume/volatility indicators — overrides fetch()/_persist() entirely rather
    than the OHLCV-specific defaults on BaseJob."""

    job_name = "technical_indicators"

    def fetch(self, run_date: date) -> list[dict]:
        with get_conn() as conn:
            histories = fetch_lookback_history(conn, run_date)

        return [
            {"instrument_id": instrument_id, "trade_date": run_date, **compute_indicators(df)}
            for instrument_id, df in histories.items()
        ]

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        with get_conn() as conn:
            return bulk_upsert_technical_indicators(conn, rows)
