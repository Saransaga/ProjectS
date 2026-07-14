"""Mirrors scheduler.py's `daily_brokerage_ingest` (17:00 IST daily).
consensus_ratings recomputes from brokerage_calls + the latest close, so it
runs after brokerage_calls in this DAG — same ordering as scheduler.py's
comment. Its dependency on the same day's equity close (from the 16:00
daily_eod_ingest DAG) is trusted to the wall-clock gap between the two
DAGs' schedules, same as the original scheduler.py did — no cross-DAG
sensor is added here, since scheduler.py never enforced that either."""

from airflow import DAG

from _ingestion_docker import DEFAULT_ARGS, START_DATE, ingestion_task

with DAG(
    dag_id="daily_brokerage_ingest",
    description="Moneycontrol brokerage calls + consensus rating recompute",
    schedule_interval="0 17 * * *",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["domain-5"],
) as dag:
    brokerage_calls = ingestion_task("brokerage_calls", "brokerage_calls")
    consensus_ratings = ingestion_task("consensus_ratings", "consensus_ratings")

    brokerage_calls >> consensus_ratings
