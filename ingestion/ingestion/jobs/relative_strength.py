from datetime import date

from ..analytics.history import fetch_lookback_history
from ..db import get_conn
from ..momentum.relative_strength import compute_composite_score, compute_returns, compute_rs_ratings
from ..upsert_relative_strength import bulk_upsert_relative_strength
from .base import BaseJob

_NIFTY_50_SYMBOL = "Nifty 50"


class RelativeStrengthJob(BaseJob):
    """Reads ohlcv_daily (not an external source, like TechnicalIndicatorsJob
    — reuses the same fetch_lookback_history helper) and computes each
    equity's trailing total return, that same return relative to Nifty 50,
    and an IBD-style RS Rating percentile across every equity with a full
    composite score that day (see momentum/relative_strength.py). Must run
    after EquityEodJob/IndexEodJob for run_date — needs both the stock's and
    Nifty 50's own close on that date."""

    job_name = "relative_strength"

    def fetch(self, run_date: date) -> list[dict]:
        with get_conn() as conn:
            histories = fetch_lookback_history(conn, run_date)
            equity_ids = self._equity_instrument_ids(conn, list(histories))
            nifty_id = self._nifty_instrument_id(conn)

        nifty_df = histories.get(nifty_id) if nifty_id is not None else None
        nifty_returns = compute_returns(nifty_df) if nifty_df is not None else {}

        per_instrument_returns: dict[int, dict] = {}
        composite_scores: dict[int, float] = {}
        for instrument_id in equity_ids:
            df = histories.get(instrument_id)
            if df is None:
                continue
            returns = compute_returns(df)
            per_instrument_returns[instrument_id] = returns
            score = compute_composite_score(returns)
            if score is not None:
                composite_scores[instrument_id] = score

        ratings = compute_rs_ratings(composite_scores)

        rows = []
        for instrument_id, returns in per_instrument_returns.items():
            rows.append(
                {
                    "instrument_id": instrument_id,
                    "trade_date": run_date,
                    "return_1w": returns["1w"],
                    "return_1m": returns["1m"],
                    "return_3m": returns["3m"],
                    "return_6m": returns["6m"],
                    "return_1y": returns["1y"],
                    "relative_return_1w": self._relative(returns["1w"], nifty_returns.get("1w")),
                    "relative_return_1m": self._relative(returns["1m"], nifty_returns.get("1m")),
                    "relative_return_3m": self._relative(returns["3m"], nifty_returns.get("3m")),
                    "relative_return_6m": self._relative(returns["6m"], nifty_returns.get("6m")),
                    "relative_return_1y": self._relative(returns["1y"], nifty_returns.get("1y")),
                    "rs_rating": ratings.get(instrument_id),
                }
            )
        return rows

    def _relative(self, stock_return: float | None, nifty_return: float | None) -> float | None:
        if stock_return is None or nifty_return is None:
            return None
        return stock_return - nifty_return

    def _equity_instrument_ids(self, conn, instrument_ids: list[int]) -> list[int]:
        if not instrument_ids:
            return []
        with conn.cursor() as cur:
            cur.execute(
                "SELECT instrument_id FROM instruments WHERE instrument_id = ANY(%s) AND instrument_type = 'EQUITY'",
                (instrument_ids,),
            )
            return [row[0] for row in cur.fetchall()]

    def _nifty_instrument_id(self, conn) -> int | None:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT instrument_id FROM instruments WHERE exchange = 'NSE' AND instrument_type = 'INDEX' AND symbol = %s",
                (_NIFTY_50_SYMBOL,),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        with get_conn() as conn:
            return bulk_upsert_relative_strength(conn, rows)
