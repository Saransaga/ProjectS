"""Mirrors scheduler.py's `announcements_poll` (every 5 min, 09:00-15:59
IST, Mon-Fri). NSE/BSE announcements have no interdependency, run in
parallel.

Known behavior delta from the original: scheduler.py's cron fires on this
same coarse hour range (cron can't express a 09:15-15:30 boundary at
minute granularity), but then calls `is_market_hours()` in Python
(`_run_announcement_jobs`) to trim the ~09:00-09:14 and ~15:31-15:59
fringe ticks down to a no-op before actually fetching. That Python-level
check lives in the ingestion image (`holiday_calendar.is_market_hours`),
not in Airflow's own process, so this DAG doesn't replicate it — the
fringe ticks here will actually call the jobs instead of no-op'ing.
Per scheduler.py's own comment this is "a cheap no-op instead of a wasted
fetch" even in the original design, so the fringe extra calls are low-risk,
not a functional regression — but worth knowing this is a real, documented
difference, not an oversight."""

from airflow import DAG

from _ingestion_docker import DEFAULT_ARGS, START_DATE, ingestion_task

with DAG(
    dag_id="announcements_poll",
    description="NSE/BSE real-time corporate announcements",
    schedule_interval="*/5 9-15 * * mon-fri",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["domain-4"],
) as dag:
    ingestion_task("nse_announcements", "nse_announcements")
    ingestion_task("bse_announcements", "bse_announcements")
