import logging
from datetime import date

from apscheduler.schedulers.blocking import BlockingScheduler

from .holiday_calendar import is_market_hours
from .jobs.bse_announcements import BseAnnouncementsJob
from .jobs.candlestick_patterns import CandlestickPatternsJob
from .jobs.corporate_actions import CorporateActionsJob
from .jobs.equity_eod import EquityEodJob
from .jobs.financial_results import FinancialResultsJob
from .jobs.fundamental_ratios import FundamentalRatiosJob
from .jobs.index_eod import IndexEodJob
from .jobs.nse_announcements import NseAnnouncementsJob
from .jobs.reddit_sentiment import RedditSentimentJob
from .jobs.rss_news import RssNewsJob
from .jobs.shareholding_pattern import ShareholdingPatternJob
from .jobs.signal_events import SignalEventsJob
from .jobs.technical_indicators import TechnicalIndicatorsJob

logger = logging.getLogger(__name__)


def _run_jobs(*jobs):
    today = date.today()
    for job in jobs:
        try:
            status = job.run(today)
            logger.info("%s %s -> %s", job.job_name, today, status)
        except Exception:
            logger.exception("%s %s errored", job.job_name, today)


def _run_daily_eod_jobs():
    # Price ingestion first, then indicators (reads ohlcv_daily), then
    # candlesticks and signal events (the latter reads sma_50/200 crossovers
    # out of technical_indicators_daily, so it must come last).
    _run_jobs(
        EquityEodJob(),
        IndexEodJob(),
        TechnicalIndicatorsJob(),
        CandlestickPatternsJob(),
        SignalEventsJob(),
    )


def _run_daily_fundamentals_jobs():
    _run_jobs(CorporateActionsJob(), FinancialResultsJob())


def _run_weekly_fundamentals_jobs():
    # fundamental_ratios reads fundamentals_quarterly + corporate_actions, so
    # it must come after shareholding_pattern in this run.
    _run_jobs(ShareholdingPatternJob(), FundamentalRatiosJob())


def _run_announcement_jobs():
    # Cron fires every 5 min, mon-fri, 09:00-15:59 IST; is_market_hours()
    # trims that down to the actual 09:15-15:30 session so a fired-but-closed
    # tick (e.g. 09:05, 15:35) is a cheap no-op instead of a wasted fetch.
    if not is_market_hours():
        return
    _run_jobs(NseAnnouncementsJob(), BseAnnouncementsJob())


def _run_news_jobs():
    # RssNewsJob/RedditSentimentJob set always_force=True (see jobs/base.py) —
    # they don't stop at market close or on weekends/holidays the way exchange
    # filings do.
    _run_jobs(RssNewsJob(), RedditSentimentJob())


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone="Asia/Kolkata")
    # 16:00 IST — after the 15:45 bhavcopy publish time, with a buffer for
    # exchange publishing delays.
    scheduler.add_job(
        _run_daily_eod_jobs,
        "cron",
        hour=16,
        minute=0,
        id="daily_eod_ingest",
        coalesce=True,
        misfire_grace_time=3600,
    )
    # 18:30 IST — corporate actions (daily poll) + financial results
    # (board-meeting-driven, within-24h-of-filing check).
    scheduler.add_job(
        _run_daily_fundamentals_jobs,
        "cron",
        hour=18,
        minute=30,
        id="daily_fundamentals_ingest",
        coalesce=True,
        misfire_grace_time=3600,
    )
    # Sunday 20:00 IST — shareholding pattern + ratio recompute. Weekly
    # rather than the spec's literal "monthly" for shareholding: the real
    # SEBI filing deadline is a rolling ~3-week window after quarter-end, not
    # a fixed date, and the underlying call is a single cheap bulk request.
    scheduler.add_job(
        _run_weekly_fundamentals_jobs,
        "cron",
        day_of_week="sun",
        hour=20,
        minute=0,
        id="weekly_fundamentals_ingest",
        coalesce=True,
        misfire_grace_time=3600,
    )
    # Every 5 minutes, market hours only (mon-fri) — NSE/BSE corporate
    # announcements, per nse_corporate_client.fetch_corporate_announcements'
    # "Domain 4 polls every few minutes during market hours".
    scheduler.add_job(
        _run_announcement_jobs,
        "cron",
        minute="*/5",
        hour="9-15",
        day_of_week="mon-fri",
        id="announcements_poll",
        coalesce=True,
        misfire_grace_time=120,
    )
    # Every 30 minutes, every day of the week — RSS feeds + Reddit, which
    # don't stop at 15:30 or on weekends the way exchange filings do.
    scheduler.add_job(
        _run_news_jobs,
        "cron",
        minute="*/30",
        id="news_poll",
        coalesce=True,
        misfire_grace_time=300,
    )
    return scheduler
