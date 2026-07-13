import logging
from datetime import date

from ..bse_client import BseNoDataError
from ..db import get_conn
from ..holiday_calendar import is_trading_day
from ..lock import JobLock
from ..nse_client import NseNoDataError
from ..upsert import bulk_upsert_ohlcv, upsert_instrument

logger = logging.getLogger(__name__)

_NO_DATA_EXCEPTIONS = (NseNoDataError, BseNoDataError)


class BaseJob:
    job_name: str = ""

    # True for jobs whose schedule doesn't align with is_trading_day()'s
    # weekday/holiday gate: real-time feeds that always pull "whatever's
    # current right now" regardless of run_date (RSS/Reddit news, NSE/BSE
    # announcements — these should poll every day including weekends), and
    # batch jobs deliberately scheduled on a non-trading day (e.g. a weekly
    # recompute cron'd for Sunday, which is_trading_day() would otherwise
    # reject on every single run). A property on the job class rather than a
    # force=True the caller has to remember to pass, so every caller (CLI,
    # scheduler, dashboard) behaves consistently without each maintaining its
    # own allowlist.
    always_force: bool = False

    def fetch(self, run_date: date) -> list[dict]:
        """Return rows with symbol/exchange/instrument_type/series/name/isin plus
        OHLCV fields. Raise NseNoDataError/BseNoDataError if the exchange has no
        data for run_date (holiday)."""
        raise NotImplementedError

    def run(self, run_date: date, force: bool = False) -> str:
        force = force or self.always_force
        if not force and not is_trading_day(run_date):
            self._log(run_date, "SKIPPED", 0, "not a trading day (weekend/known holiday)")
            return "SKIPPED"

        with JobLock(self.job_name, run_date) as acquired:
            if not acquired:
                logger.info("%s %s: another run holds the lock, skipping", self.job_name, run_date)
                return "SKIPPED"

            if not force and self._already_succeeded(run_date):
                logger.info("%s %s: already ingested, skipping", self.job_name, run_date)
                return "SKIPPED"

            self._log(run_date, "RUNNING", None, None)
            try:
                rows = self.fetch(run_date)
            except _NO_DATA_EXCEPTIONS as exc:
                self._log(run_date, "SKIPPED", 0, str(exc))
                return "SKIPPED"
            except Exception as exc:
                logger.exception("%s %s failed", self.job_name, run_date)
                self._log(run_date, "FAILED", None, str(exc))
                raise

            try:
                count = self._persist(run_date, rows)
            except Exception as exc:
                logger.exception("%s %s failed while persisting", self.job_name, run_date)
                self._log(run_date, "FAILED", None, str(exc))
                raise

            self._log(run_date, "SUCCESS", count, None)
            return "SUCCESS"

    def _persist(self, run_date: date, rows: list[dict]) -> int:
        with get_conn() as conn:
            ohlcv_rows = []
            for r in rows:
                instrument_id = upsert_instrument(
                    conn,
                    symbol=r["symbol"],
                    exchange=r["exchange"],
                    instrument_type=r["instrument_type"],
                    trade_date=run_date,
                    series=r.get("series"),
                    name=r.get("name"),
                    isin=r.get("isin"),
                )
                ohlcv_rows.append({**r, "instrument_id": instrument_id, "trade_date": run_date})

            count = bulk_upsert_ohlcv(conn, ohlcv_rows)
        # upsert transaction committed above; refresh_continuous_aggregate is a
        # procedure that commits internally, so it must run as the sole
        # statement in its own (autocommit) transaction, not nested with the
        # upserts.
        with get_conn() as conn:
            conn.autocommit = True
            try:
                with conn.cursor() as cur:
                    cur.execute("CALL refresh_continuous_aggregate('ohlcv_weekly', NULL, NULL)")
            finally:
                conn.autocommit = False

        return count

    def _already_succeeded(self, run_date: date) -> bool:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM ingestion_log WHERE job_name = %s AND run_date = %s",
                (self.job_name, run_date),
            )
            row = cur.fetchone()
            return row is not None and row[0] == "SUCCESS"

    def _log(self, run_date: date, status: str, rows_ingested: int | None, error: str | None) -> None:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_log (job_name, run_date, status, rows_ingested, error, finished_at)
                VALUES (%s, %s, %s, %s, %s, CASE WHEN %s = 'RUNNING' THEN NULL ELSE now() END)
                ON CONFLICT (job_name, run_date) DO UPDATE SET
                    status = EXCLUDED.status,
                    rows_ingested = EXCLUDED.rows_ingested,
                    error = EXCLUDED.error,
                    finished_at = EXCLUDED.finished_at
                """,
                (self.job_name, run_date, status, rows_ingested, error, status),
            )
