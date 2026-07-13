import logging
from datetime import date

from ..analytics.history import fetch_lookback_history
from ..analytics.signals import (
    compute_support_resistance,
    detect_52w_proximity,
    detect_breakout_breakdown,
    detect_golden_death_cross,
)
from ..db import get_conn
from ..upsert_analytics import replace_signal_events, replace_support_resistance_levels
from .base import BaseJob

logger = logging.getLogger(__name__)


class SignalEventsJob(BaseJob):
    """Reads ohlcv_daily plus the SMA 50/200 crossover inputs from
    technical_indicators_daily (must have run for run_date and the prior
    trading day — this job is sequenced after TechnicalIndicatorsJob) and
    detects breakout/breakdown, 52-week proximity, golden/death cross, and
    pivot-based support/resistance levels."""

    job_name = "signal_events"

    def fetch(self, run_date: date) -> list[dict]:
        with get_conn() as conn:
            histories = fetch_lookback_history(conn, run_date)
            sma_by_instrument = self._fetch_sma_cross_inputs(conn, run_date, list(histories.keys()))

        results = []
        for instrument_id, df in histories.items():
            events = detect_52w_proximity(df)

            breakout = detect_breakout_breakdown(df)
            if breakout:
                events.append(breakout)

            cross_rows = sma_by_instrument.get(instrument_id)
            if cross_rows and len(cross_rows) == 2 and cross_rows[0][0] == run_date:
                (_, curr_50, curr_200), (_, prev_50, prev_200) = cross_rows
                cross_type = detect_golden_death_cross(prev_50, prev_200, curr_50, curr_200)
                if cross_type:
                    events.append(
                        {
                            "event_type": cross_type,
                            "details": {
                                "sma_50": curr_50,
                                "sma_200": curr_200,
                                "prev_sma_50": prev_50,
                                "prev_sma_200": prev_200,
                            },
                        }
                    )

            results.append(
                {
                    "instrument_id": instrument_id,
                    "events": events,
                    "levels": compute_support_resistance(df),
                }
            )
        return results

    def _fetch_sma_cross_inputs(self, conn, run_date: date, instrument_ids: list[int]) -> dict:
        """Latest two technical_indicators_daily rows (sma_50, sma_200) at or
        before run_date, per instrument."""
        if not instrument_ids:
            return {}
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT instrument_id, trade_date, sma_50, sma_200 FROM (
                    SELECT instrument_id, trade_date, sma_50, sma_200,
                           ROW_NUMBER() OVER (PARTITION BY instrument_id ORDER BY trade_date DESC) AS rn
                    FROM technical_indicators_daily
                    WHERE instrument_id = ANY(%s) AND trade_date <= %s
                ) ranked
                WHERE rn <= 2
                ORDER BY instrument_id, trade_date DESC
                """,
                (instrument_ids, run_date),
            )
            rows = cur.fetchall()

        by_instrument: dict[int, list[tuple]] = {}
        for instrument_id, trade_date, sma_50, sma_200 in rows:
            by_instrument.setdefault(instrument_id, []).append(
                (trade_date, None if sma_50 is None else float(sma_50), None if sma_200 is None else float(sma_200))
            )
        return by_instrument

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        with get_conn() as conn:
            event_rows = [
                {"instrument_id": r["instrument_id"], "event_date": run_date, **event}
                for r in rows
                for event in r["events"]
            ]
            instrument_ids = [r["instrument_id"] for r in rows]
            event_count = replace_signal_events(conn, run_date, instrument_ids, event_rows)

            level_count = 0
            for r in rows:
                level_count += replace_support_resistance_levels(conn, r["instrument_id"], run_date, r["levels"])

        logger.info("%s %s: %d events, %d support/resistance levels", self.job_name, run_date, event_count, level_count)
        return event_count
