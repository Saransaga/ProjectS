"""Mirrors scheduler.py's `monthly_industry_classification` (1st of month,
08:30 IST) — NSE Indices' sectoral-index constituent CSVs change rarely,
monthly is plenty (same cadence class as monthly_index_rebalancing)."""

from airflow import DAG

from _ingestion_docker import DEFAULT_ARGS, START_DATE, ingestion_task

with DAG(
    dag_id="monthly_industry_classification",
    description="Sector/industry classification from NSE sectoral-index constituents",
    schedule_interval="30 8 1 * *",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["domain-8"],
) as dag:
    ingestion_task("industry_classification", "industry_classification")
