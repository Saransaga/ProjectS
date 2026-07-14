"""Mirrors scheduler.py's `daily_eod_ingest` (16:00 IST daily): equity/index
price ingestion, then the analytics chain that reads it. Original code ran
all five sequentially in one process; equity and index have no
interdependency (both are independent EOD ingests, per Domain 1), so they
run in parallel here — technical_indicators still waits on both, matching
the "price ingestion first, then indicators" ordering from scheduler.py's
own comment."""

from airflow import DAG

from _ingestion_docker import DEFAULT_ARGS, START_DATE, ingestion_task

with DAG(
    dag_id="daily_eod_ingest",
    description="NSE equity/index EOD + technical indicators/candlesticks/signal events",
    schedule_interval="0 16 * * *",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["domain-1", "domain-2"],
) as dag:
    equity = ingestion_task("equity", "nse_equity_eod")
    index = ingestion_task("index", "index_eod")
    technical_indicators = ingestion_task("technical_indicators", "technical_indicators")
    candlestick_patterns = ingestion_task("candlestick_patterns", "candlestick_patterns")
    signal_events = ingestion_task("signal_events", "signal_events")

    [equity, index] >> technical_indicators >> candlestick_patterns >> signal_events
