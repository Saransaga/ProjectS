"""Mirrors scheduler.py's `fii_dii_ingest` (18:00 IST daily) — a single
job. Kept as its own DAG (not folded into daily_momentum_ingest) because
NSE's fiidiiTradeReact endpoint publishes on its own ~18:00 schedule,
independent of the 17:15 F&O slot — same reasoning as scheduler.py's
separate cron entry."""

from airflow import DAG

from _ingestion_docker import DEFAULT_ARGS, START_DATE, ingestion_task

with DAG(
    dag_id="fii_dii_ingest",
    description="Cash-market FII/DII net buy/sell + F&O participant OI",
    schedule_interval="0 18 * * *",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["domain-6"],
) as dag:
    ingestion_task("fii_dii_flows", "fii_dii_flows")
