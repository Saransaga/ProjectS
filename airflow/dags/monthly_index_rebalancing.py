"""Mirrors scheduler.py's `monthly_index_rebalancing` (1st of month, 09:00
IST) — NSE Indices' rebalancing-cadence page changes rarely, monthly is
plenty."""

from airflow import DAG

from _ingestion_docker import DEFAULT_ARGS, START_DATE, ingestion_task

with DAG(
    dag_id="monthly_index_rebalancing",
    description="NSE Indices rebalancing-cadence refresh",
    schedule_interval="0 9 1 * *",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["domain-7"],
) as dag:
    ingestion_task("index_rebalancing_schedule", "index_rebalancing_schedule")
