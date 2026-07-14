"""Mirrors scheduler.py's `weekly_fundamentals_ingest` (Sun 20:00 IST).
fundamental_ratios must come after shareholding_pattern in this run, per
scheduler.py's own comment. Weekly rather than the domain spec's literal
"monthly": the real SEBI filing deadline is a rolling ~3-week window after
quarter-end, not a fixed date, and the underlying call is a single cheap
bulk request — see README.md's Domain 3 section."""

from airflow import DAG

from _ingestion_docker import DEFAULT_ARGS, START_DATE, ingestion_task

with DAG(
    dag_id="weekly_fundamentals_ingest",
    description="Shareholding pattern + fundamental ratio recompute",
    schedule_interval="0 20 * * sun",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["domain-3"],
) as dag:
    shareholding_pattern = ingestion_task("shareholding_pattern", "shareholding_pattern")
    fundamental_ratios = ingestion_task("fundamental_ratios", "fundamental_ratios")

    shareholding_pattern >> fundamental_ratios
