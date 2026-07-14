"""Mirrors scheduler.py's `bulk_block_deals_poll` (12:00 & 16:00 IST,
Mon-Fri) — 2 intraday windows per the domain spec, since bulk.csv/block.csv
only ever serve "today's" running list (always_force=True)."""

from airflow import DAG

from _ingestion_docker import DEFAULT_ARGS, START_DATE, ingestion_task

with DAG(
    dag_id="bulk_block_deals_poll",
    description="NSE bulk/block deals, 2 intraday windows",
    schedule_interval="0 12,16 * * mon-fri",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["domain-6"],
) as dag:
    ingestion_task("bulk_block_deals", "bulk_block_deals")
