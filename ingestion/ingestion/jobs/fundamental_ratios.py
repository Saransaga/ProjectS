from datetime import date, timedelta

from ..db import get_conn
from ..fundamentals.ratios import compute_dividend_yield, compute_payout_ratio, compute_pe_ratio, compute_ps_ratio, trailing_sum
from ..upsert_fundamentals import bulk_upsert_fundamental_ratios
from .base import BaseJob

_TRAILING_QUARTERS = 4
_TRAILING_DIVIDEND_DAYS = 365


class FundamentalRatiosJob(BaseJob):
    """Weekly recompute of P/E, P/S, dividend yield, and payout ratio from
    fundamentals_quarterly + the latest close (ohlcv_daily) + trailing
    dividends (corporate_actions). P/B, EV/EBITDA, P/FCF, Forward P/E,
    ROE/ROCE/ROA need annual balance-sheet/cash-flow data or consensus
    estimates not collected in this phase — left NULL, see README.

    always_force=True: scheduled for Sunday (see scheduler.py), which
    is_trading_day() always rejects — without this, the weekly cron would
    SKIPPED every single run and this table would never get populated."""

    job_name = "fundamental_ratios"
    always_force = True

    def fetch(self, run_date: date) -> list[dict]:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT instrument_id FROM fundamentals_quarterly")
                instrument_ids = [row[0] for row in cur.fetchall()]

            results = []
            for instrument_id in instrument_ids:
                quarters = self._latest_quarters(conn, instrument_id)
                if not quarters:
                    continue
                price = self._latest_close(conn, instrument_id)
                if price is None:
                    continue

                trailing_eps = trailing_sum([q["eps_basic"] for q in quarters], _TRAILING_QUARTERS)
                trailing_revenue = trailing_sum([q["revenue"] for q in quarters], _TRAILING_QUARTERS)
                shares_outstanding = quarters[-1]["shares_outstanding"]
                trailing_dividends = self._trailing_dividends_per_share(conn, instrument_id, run_date)

                results.append(
                    {
                        "instrument_id": instrument_id,
                        "as_of_date": run_date,
                        "pe_ratio": compute_pe_ratio(price, trailing_eps),
                        "ps_ratio": compute_ps_ratio(price, shares_outstanding, trailing_revenue),
                        # trailing_dividends is always a float (COALESCE(...,0) in
                        # _trailing_dividends_per_share), and 0.0 is a real "no
                        # dividends paid" signal, not missing data — don't guard on
                        # its truthiness, let compute_*'s own price/eps checks decide.
                        "dividend_yield": compute_dividend_yield(price, trailing_dividends),
                        "payout_ratio": compute_payout_ratio(trailing_dividends, trailing_eps),
                    }
                )
        return results

    def _latest_quarters(self, conn, instrument_id: int) -> list[dict]:
        """Most recent distinct reporting periods, preferring the consolidated
        figure over standalone when both exist for the same period, oldest
        first (so trailing_sum's values[-n:] lines up)."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT period_end_date, eps_basic, revenue, shares_outstanding
                FROM (
                    SELECT DISTINCT ON (period_end_date) period_end_date, eps_basic, revenue, shares_outstanding
                    FROM fundamentals_quarterly
                    WHERE instrument_id = %s
                    ORDER BY period_end_date DESC, consolidated DESC
                ) recent
                ORDER BY period_end_date DESC
                LIMIT %s
                """,
                (instrument_id, _TRAILING_QUARTERS),
            )
            rows = cur.fetchall()
        # NUMERIC columns come back as Decimal; ratios.py mixes these with a
        # plain float price, so normalize to float here rather than in every
        # pure function.
        quarters = [
            {
                "period_end_date": r[0],
                "eps_basic": None if r[1] is None else float(r[1]),
                "revenue": None if r[2] is None else float(r[2]),
                "shares_outstanding": r[3],
            }
            for r in rows
        ]
        return sorted(quarters, key=lambda q: q["period_end_date"])

    def _latest_close(self, conn, instrument_id: int) -> float | None:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT close FROM ohlcv_daily WHERE instrument_id = %s ORDER BY trade_date DESC LIMIT 1",
                (instrument_id,),
            )
            row = cur.fetchone()
            return float(row[0]) if row else None

    def _trailing_dividends_per_share(self, conn, instrument_id: int, run_date: date) -> float:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(SUM(amount_per_share), 0) FROM corporate_actions
                WHERE instrument_id = %s AND action_type = 'DIVIDEND'
                  AND amount_per_share IS NOT NULL
                  AND ex_date BETWEEN %s AND %s
                """,
                (instrument_id, run_date - timedelta(days=_TRAILING_DIVIDEND_DAYS), run_date),
            )
            return float(cur.fetchone()[0])

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        with get_conn() as conn:
            return bulk_upsert_fundamental_ratios(conn, rows)
