import logging
from datetime import date

from apscheduler.schedulers.blocking import BlockingScheduler

from .jobs.equity_eod import EquityEodJob
from .jobs.index_eod import IndexEodJob

logger = logging.getLogger(__name__)


def _run_daily_jobs():
    today = date.today()
    for job in (EquityEodJob(), IndexEodJob()):
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
