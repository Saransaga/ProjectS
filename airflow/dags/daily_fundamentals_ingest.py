"""Mirrors scheduler.py's `daily_fundamentals_ingest` (18:30 IST daily).
No documented ordering dependency between corporate_actions and
financial_results in scheduler.py's `_run_daily_fundamentals_jobs`, so
both run in parallel here."""

from airflow import DAG

from _ingestion_docker import DEFAULT_ARGS, START_DATE, ingestion_task

with DAG(
    dag_id="daily_fundamentals_ingest",
    description="Corporate actions calendar poll + board-meeting-driven financial results",
    schedule_interval="30 18 * * *",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["domain-3"],
) as dag:
    ingestion_task("corporate_actions", "corporate_actions")
    ingestion_task("financial_results", "financial_results")
