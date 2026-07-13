import logging
from datetime import date

from apscheduler.schedulers.blocking import BlockingScheduler

from .jobs.candlestick_patterns import CandlestickPatternsJob
from .jobs.equity_eod import EquityEodJob
from .jobs.index_eod import IndexEodJob
from .jobs.signal_events import SignalEventsJob
from .jobs.technical_indicators import TechnicalIndicatorsJob

logger = logging.getLogger(__name__)


def _run_daily_jobs():
    today = date.today()
    # Price ingestion first, then indicators (reads ohlcv_daily), then
    # candlesticks and signal events (the latter reads sma_50/200 crossovers
    # out of technical_indicators_daily, so it must come last).
    jobs = (
        EquityEodJob(),
        IndexEodJob(),
        TechnicalIndicatorsJob(),
        CandlestickPatternsJob(),
        SignalEventsJob(),
    )
    for job in jobs:
        try:
            status = job.run(today)
            logger.info("%s %s -> %s", job.job_name, today, status)
        except Exception:
            logger.exception("%s %s errored", job.job_name, today)


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone="Asia/Kolkata")
    # 16:00 IST — after the 15:45 bhavcopy publish time, with a buffer for
    # exchange publishing delays.
    scheduler.add_job(
        _run_daily_jobs,
        "cron",
        hour=16,
        minute=0,
        id="daily_eod_ingest",
        coalesce=True,
        misfire_grace_time=3600,
    )
    return scheduler
