"""Per-job expected-run cadence, transcribed from README.md's job schedule
table — pure data, no I/O. Lets "is this job up to date" be judged against
its OWN expected frequency instead of one global staleness threshold: a job
due every 5 minutes going stale for 2 hours is a very different signal than a
monthly job being 3 weeks past its last run. Keyed by each job class's own
`job_name` attribute (ingestion_log.job_name), not the CLI's `--job` group
names.

`grace_hours`: how far past the expected next-run time a job can drift before
it's considered STALE rather than merely DUE. Chosen generously relative to
each cadence (a few missed ticks for intraday jobs, a day+ for daily jobs) so
the scheduled 21:45-07:45 IST downtime window (docs/OPERATIONS.md) doesn't
itself flag every daily job STALE every single morning.
"""

from datetime import datetime, timedelta
from enum import Enum
from zoneinfo import ZoneInfo


class Cadence(str, Enum):
    INTRADAY = "INTRADAY"  # runs every N minutes, possibly market-hours-only
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


# minutes: only for INTRADAY. hour: IST hour of the (last) daily run. day_of_week:
# only for WEEKLY (0=Mon). day_of_month: only for MONTHLY. market_hours_only:
# INTRADAY jobs that only tick 09:15-15:30 IST, Mon-Fri.
JOB_CADENCE: dict[str, dict] = {
    # Domain 1 — daily 16:00 IST
    "nse_equity_eod": {"cadence": Cadence.DAILY, "hour": 16, "grace_hours": 27},
    "index_eod": {"cadence": Cadence.DAILY, "hour": 16, "grace_hours": 27},
    # Domain 2 — daily 16:00 IST, after equity/index
    "technical_indicators": {"cadence": Cadence.DAILY, "hour": 16, "grace_hours": 27},
    "candlestick_patterns": {"cadence": Cadence.DAILY, "hour": 16, "grace_hours": 27},
    "signal_events": {"cadence": Cadence.DAILY, "hour": 16, "grace_hours": 27},
    # Domain 3 — actions/results daily 18:30 IST; ratios/shareholding weekly Sun 20:00 IST
    "corporate_actions": {"cadence": Cadence.DAILY, "hour": 18, "grace_hours": 27},
    "financial_results": {"cadence": Cadence.DAILY, "hour": 18, "grace_hours": 27},
    "shareholding_pattern": {"cadence": Cadence.WEEKLY, "day_of_week": 6, "grace_hours": 60},
    "fundamental_ratios": {"cadence": Cadence.WEEKLY, "day_of_week": 6, "grace_hours": 60},
    # Domain 4 — announcements every 5 min market hours; news every 30 min around the clock
    "nse_announcements": {"cadence": Cadence.INTRADAY, "minutes": 5, "market_hours_only": True, "grace_hours": 2},
    "bse_announcements": {"cadence": Cadence.INTRADAY, "minutes": 5, "market_hours_only": True, "grace_hours": 2},
    "rss_news": {"cadence": Cadence.INTRADAY, "minutes": 30, "grace_hours": 3},
    "reddit_sentiment": {"cadence": Cadence.INTRADAY, "minutes": 30, "grace_hours": 3},
    # Domain 5 — daily 17:00 IST, after equity/index
    "brokerage_calls": {"cadence": Cadence.DAILY, "hour": 17, "grace_hours": 27},
    "consensus_ratings": {"cadence": Cadence.DAILY, "hour": 17, "grace_hours": 27},
    # Domain 6 — 17:15/18:00 IST daily, bulk/block deals also intraday
    "fno_bhavcopy": {"cadence": Cadence.DAILY, "hour": 17, "grace_hours": 27},
    "fno_signals": {"cadence": Cadence.DAILY, "hour": 17, "grace_hours": 27},
    "deliverable_volume": {"cadence": Cadence.DAILY, "hour": 17, "grace_hours": 27},
    "relative_strength": {"cadence": Cadence.DAILY, "hour": 17, "grace_hours": 27},
    "fii_dii_flows": {"cadence": Cadence.DAILY, "hour": 18, "grace_hours": 27},
    "bulk_block_deals": {"cadence": Cadence.INTRADAY, "minutes": 240, "market_hours_only": True, "grace_hours": 8},
    # Domain 7 — daily 19:00 IST, index rebalancing monthly 1st 09:00 IST
    "corporate_calendar": {"cadence": Cadence.DAILY, "hour": 19, "grace_hours": 27},
    "ipo_listings": {"cadence": Cadence.DAILY, "hour": 19, "grace_hours": 27},
    "index_rebalancing_schedule": {"cadence": Cadence.MONTHLY, "day_of_month": 1, "grace_hours": 96},
    # Domain 8 — classification monthly 1st 08:30 IST; recompute + outcome tracking daily 21:00 IST
    "industry_classification": {"cadence": Cadence.MONTHLY, "day_of_month": 1, "grace_hours": 96},
    "recommendation_engine": {"cadence": Cadence.DAILY, "hour": 21, "grace_hours": 27},
    "recommendation_outcomes": {"cadence": Cadence.DAILY, "hour": 21, "grace_hours": 27},
    "telegram_alerts": {"cadence": Cadence.DAILY, "hour": 21, "grace_hours": 27},
}

_IST = ZoneInfo("Asia/Kolkata")


def classify_freshness(job_name: str, last_finished_at: datetime | None, now: datetime | None = None) -> str:
    """FRESH/DUE/STALE for one job's most recent successful ingestion_log
    finished_at, judged against its own cadence's grace_hours — not a single
    global threshold (see module docstring). Unknown job_name (e.g. a job
    added to the codebase but not yet to JOB_CADENCE) or a job that has never
    run returns "UNKNOWN" rather than a guessed status."""
    if last_finished_at is None:
        return "UNKNOWN"
    cadence = JOB_CADENCE.get(job_name)
    if cadence is None:
        return "UNKNOWN"

    now = now or datetime.now(_IST)
    if last_finished_at.tzinfo is None:
        last_finished_at = last_finished_at.replace(tzinfo=_IST)

    age_hours = (now - last_finished_at).total_seconds() / 3600.0
    grace_hours = cadence["grace_hours"]
    if cadence["cadence"] == Cadence.INTRADAY:
        expected_gap_hours = cadence["minutes"] / 60.0
    elif cadence["cadence"] == Cadence.DAILY:
        expected_gap_hours = 24.0
    elif cadence["cadence"] == Cadence.WEEKLY:
        expected_gap_hours = 7 * 24.0
    else:  # MONTHLY
        expected_gap_hours = 31 * 24.0

    if age_hours <= expected_gap_hours:
        return "FRESH"
    if age_hours <= expected_gap_hours + grace_hours:
        return "DUE"
    return "STALE"
