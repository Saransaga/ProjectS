import logging
from datetime import datetime, timedelta

import click

from .jobs.brokerage_calls import BrokerageCallsJob
from .jobs.bse_announcements import BseAnnouncementsJob
from .jobs.bulk_block_deals import BulkBlockDealsJob
from .jobs.candlestick_patterns import CandlestickPatternsJob
from .jobs.consensus_ratings import ConsensusRatingsJob
from .jobs.corporate_actions import CorporateActionsJob
from .jobs.deliverable_volume import DeliverableVolumeJob
from .jobs.equity_eod import EquityEodJob
from .jobs.fii_dii_flows import FiiDiiFlowsJob
from .jobs.financial_results import FinancialResultsJob
from .jobs.fno_bhavcopy import FnoBhavcopyJob
from .jobs.fno_signals import FnoSignalsJob
from .jobs.fundamental_ratios import FundamentalRatiosJob
from .jobs.index_eod import IndexEodJob
from .jobs.nse_announcements import NseAnnouncementsJob
from .jobs.reddit_sentiment import RedditSentimentJob
from .jobs.relative_strength import RelativeStrengthJob
from .jobs.rss_news import RssNewsJob
from .jobs.shareholding_pattern import ShareholdingPatternJob
from .jobs.signal_events import SignalEventsJob
from .jobs.technical_indicators import TechnicalIndicatorsJob

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# technical_indicators reads ohlcv_daily, so it must follow equity/index; signal_events
# reads technical_indicators_daily (SMA 50/200 crossovers), so it must follow that.
_ANALYTICS_JOBS = [TechnicalIndicatorsJob, CandlestickPatternsJob, SignalEventsJob]

# fundamental_ratios reads fundamentals_quarterly + corporate_actions, so it must run last.
_FUNDAMENTALS_JOBS = [CorporateActionsJob, ShareholdingPatternJob, FinancialResultsJob, FundamentalRatiosJob]

# Exchange announcements (NSE/BSE) — real-time feeds, no interdependency.
_ANNOUNCEMENTS_JOBS = [NseAnnouncementsJob, BseAnnouncementsJob]

# RSS + Reddit — news doesn't stop on weekends/holidays; always_force=True on
# the job classes themselves (see jobs/base.py) bypasses the is_trading_day
# gate, so no special-casing is needed here.
_NEWS_JOBS = [RssNewsJob, RedditSentimentJob]

# consensus_ratings recomputes from brokerage_calls + the latest close, so it
# must run after brokerage_calls (and after equity, for that latest close).
_BROKERAGE_JOBS = [BrokerageCallsJob, ConsensusRatingsJob]

# fno_signals reads fno_bhavcopy_daily, so it must follow fno_bhavcopy.
# deliverable_volume/relative_strength/fii_dii_flows have no interdependency
# with each other, but all read/enrich same-day ohlcv_daily rows, so this
# whole group is meant to run after `equity`/`index` (see scheduler.py).
_MOMENTUM_JOBS = [
    FiiDiiFlowsJob,
    BulkBlockDealsJob,
    FnoBhavcopyJob,
    FnoSignalsJob,
    DeliverableVolumeJob,
    RelativeStrengthJob,
]

_JOBS = {
    "equity": [EquityEodJob],
    "index": [IndexEodJob],
    "analytics": _ANALYTICS_JOBS,
    "fundamentals": _FUNDAMENTALS_JOBS,
    "announcements": _ANNOUNCEMENTS_JOBS,
    "news": _NEWS_JOBS,
    "brokerage": _BROKERAGE_JOBS,
    "momentum": _MOMENTUM_JOBS,
    "all": [
        EquityEodJob,
        IndexEodJob,
        *_ANALYTICS_JOBS,
        *_FUNDAMENTALS_JOBS,
        *_ANNOUNCEMENTS_JOBS,
        *_NEWS_JOBS,
        *_BROKERAGE_JOBS,
        *_MOMENTUM_JOBS,
    ],
}


@click.group()
def cli():
    pass


@cli.command()
@click.option("--job", type=click.Choice(list(_JOBS)), default="all")
@click.option("--date", "date_str", required=True, help="YYYY-MM-DD")
@click.option("--force", is_flag=True, help="Re-run even if already SUCCESS for this date")
def backfill(job, date_str, force):
    run_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    for job_cls in _JOBS[job]:
        status = job_cls().run(run_date, force=force)
        click.echo(f"{job_cls.job_name} {run_date} -> {status}")


@cli.command(name="backfill-range")
@click.option("--job", type=click.Choice(list(_JOBS)), default="all")
@click.option("--from", "from_str", required=True, help="YYYY-MM-DD")
@click.option("--to", "to_str", required=True, help="YYYY-MM-DD")
@click.option("--force", is_flag=True)
def backfill_range(job, from_str, to_str, force):
    start = datetime.strptime(from_str, "%Y-%m-%d").date()
    end = datetime.strptime(to_str, "%Y-%m-%d").date()
    d = start
    while d <= end:
        for job_cls in _JOBS[job]:
            status = job_cls().run(d, force=force)
            click.echo(f"{job_cls.job_name} {d} -> {status}")
        d += timedelta(days=1)


if __name__ == "__main__":
    cli()
