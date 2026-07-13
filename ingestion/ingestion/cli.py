import logging
from datetime import datetime, timedelta

import click

from .jobs.candlestick_patterns import CandlestickPatternsJob
from .jobs.equity_eod import EquityEodJob
from .jobs.index_eod import IndexEodJob
from .jobs.signal_events import SignalEventsJob
from .jobs.technical_indicators import TechnicalIndicatorsJob

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# technical_indicators reads ohlcv_daily, so it must follow equity/index; signal_events
# reads technical_indicators_daily (SMA 50/200 crossovers), so it must follow that.
_ANALYTICS_JOBS = [TechnicalIndicatorsJob, CandlestickPatternsJob, SignalEventsJob]

_JOBS = {
    "equity": [EquityEodJob],
    "index": [IndexEodJob],
    "analytics": _ANALYTICS_JOBS,
    "all": [EquityEodJob, IndexEodJob, *_ANALYTICS_JOBS],
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
