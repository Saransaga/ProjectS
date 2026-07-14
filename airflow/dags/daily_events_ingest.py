"""Mirrors scheduler.py's `daily_events_ingest` (19:00 IST daily).
corporate_calendar/ipo_listings both always_force=True (NSE's feeds always
serve "whatever's current"), no ordering dependency between them — same
comment as scheduler.py's `_run_daily_events_jobs`."""

from airflow import DAG

from _ingestion_docker import DEFAULT_ARGS, START_DATE, ingestion_task

with DAG(
    dag_id="daily_events_ingest",
    description="Corporate calendar (earnings/dividend/bonus/split/AGM/EGM) + IPO calendar",
    schedule_interval="0 19 * * *",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["domain-7"],
) as dag:
    ingestion_task("corporate_calendar", "corporate_calendar")
    ingestion_task("ipo_listings", "ipo_listings")
