from datetime import date

from ..db import get_conn
from ..momentum.oi_buildup import classify_buildup
from ..momentum.pcr import compute_max_pain, compute_pcr
from ..momentum.rollover import compute_rollover_pct
from ..upsert_fno import bulk_upsert_fno_oi_buildup, bulk_upsert_fno_rollover, bulk_upsert_fno_signals
from .base import BaseJob


class FnoSignalsJob(BaseJob):
    """Reads fno_bhavcopy_daily for run_date (must run after FnoBhavcopyJob
    for the same date, not an external source itself) and computes three
    derived views per underlying:

    - fno_signals: PCR (OI-based and volume-based) + max-pain strike per
      (underlying, expiry) option chain. "Market-wide" PCR per the domain
      spec is just the underlying_symbol='NIFTY' rows here.
    - fno_oi_buildup: futures OI-buildup classification per (underlying,
      expiry) — uses the bhavcopy's own PrvsClsgPric/ChngInOpnIntrst fields
      directly, so no separate prior-day lookup is needed.
    - fno_rollover: one row per underlying, comparing its two nearest live
      futures expiries' OI.
    """

    job_name = "fno_signals"

    def fetch(self, run_date: date) -> dict:
        with get_conn() as conn:
            contracts = self._fetch_contracts(conn, run_date)

        options_by_key: dict[tuple, list[dict]] = {}
        futures_by_key: dict[tuple, dict] = {}
        futures_by_underlying: dict[str, list[tuple]] = {}

        for c in contracts:
            key = (c["underlying_symbol"], c["expiry_date"])
            if c["contract_type"] == "OPT":
                options_by_key.setdefault(key, []).append(c)
            else:
                futures_by_key[key] = c
                futures_by_underlying.setdefault(c["underlying_symbol"], []).append((c["expiry_date"], c))

        signal_rows = self._build_signal_rows(run_date, options_by_key)
        buildup_rows = self._build_buildup_rows(run_date, futures_by_key)
        rollover_rows = self._build_rollover_rows(run_date, futures_by_underlying)

        return {"signals": signal_rows, "buildup": buildup_rows, "rollover": rollover_rows}

    def _fetch_contracts(self, conn, run_date: date) -> list[dict]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT underlying_symbol, contract_type, expiry_date, option_type, strike_price,
                       close_price, prev_close, open_interest, change_in_oi, volume
                FROM fno_bhavcopy_daily
                WHERE trade_date = %s
                """,
                (run_date,),
            )
            rows = cur.fetchall()
        return [
            {
                "underlying_symbol": r[0],
                "contract_type": r[1],
                "expiry_date": r[2],
                "option_type": r[3],
                "strike_price": None if r[4] is None else float(r[4]),
                "close_price": None if r[5] is None else float(r[5]),
                "prev_close": None if r[6] is None else float(r[6]),
                "open_interest": r[7],
                "change_in_oi": r[8],
                "volume": r[9],
            }
            for r in rows
        ]

    def _build_signal_rows(self, run_date: date, options_by_key: dict) -> list[dict]:
        rows = []
        for (symbol, expiry), opts in options_by_key.items():
            pcr_oi, pcr_volume = compute_pcr(opts)
            max_pain = compute_max_pain(opts)
            if pcr_oi is None and pcr_volume is None and max_pain is None:
                continue
            rows.append(
                {
                    "underlying_symbol": symbol,
                    "expiry_date": expiry,
                    "trade_date": run_date,
                    "pcr_oi": pcr_oi,
                    "pcr_volume": pcr_volume,
                    "max_pain_strike": max_pain,
                }
            )
        return rows

    def _build_buildup_rows(self, run_date: date, futures_by_key: dict) -> list[dict]:
        rows = []
        for (symbol, expiry), fut in futures_by_key.items():
            price_change_pct = self._pct_change(fut["close_price"], fut["prev_close"])
            oi_change_pct = self._oi_change_pct(fut["open_interest"], fut["change_in_oi"])
            rows.append(
                {
                    "underlying_symbol": symbol,
                    "expiry_date": expiry,
                    "trade_date": run_date,
                    "price_change_pct": price_change_pct,
                    "oi_change_pct": oi_change_pct,
                    "buildup_type": classify_buildup(price_change_pct, oi_change_pct),
                }
            )
        return rows

    def _build_rollover_rows(self, run_date: date, futures_by_underlying: dict) -> list[dict]:
        rows = []
        for symbol, futs in futures_by_underlying.items():
            futs.sort(key=lambda t: t[0])
            near_expiry, near_fut = futs[0]
            near_oi = near_fut["open_interest"] or 0

            next_expiry = next_oi = None
            if len(futs) > 1:
                next_expiry, next_fut = futs[1]
                next_oi = next_fut["open_interest"]

            rows.append(
                {
                    "underlying_symbol": symbol,
                    "trade_date": run_date,
                    "near_expiry": near_expiry,
                    "next_expiry": next_expiry,
                    "near_oi": near_oi,
                    "next_oi": next_oi,
                    "rollover_pct": compute_rollover_pct(near_oi, next_oi),
                }
            )
        return rows

    def _pct_change(self, close: float | None, prev_close: float | None) -> float | None:
        if close is None or not prev_close:
            return None
        return (close - prev_close) / prev_close * 100

    def _oi_change_pct(self, open_interest: int | None, change_in_oi: int | None) -> float | None:
        if open_interest is None or change_in_oi is None:
            return None
        prior_oi = open_interest - change_in_oi
        if not prior_oi:
            return None
        return change_in_oi / prior_oi * 100

    def _persist(self, run_date: date, rows: dict) -> int:
        with get_conn() as conn:
            signal_count = bulk_upsert_fno_signals(conn, rows["signals"])
            bulk_upsert_fno_oi_buildup(conn, rows["buildup"])
            bulk_upsert_fno_rollover(conn, rows["rollover"])
        return signal_count
