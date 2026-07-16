"""Mirrors scheduler.py's `daily_recommendation_ingest` (21:00 IST daily).
recommendation_engine recomputes from the day's technicals/momentum/
brokerage/fundamentals tables (all landed by 19:00 at the latest across the
other DAGs, trusted to the wall-clock gap same as every other cross-DAG
dependency in this project — see daily_brokerage_ingest.py's docstring).
recommendation_outcomes reads today's fresh stock_recommendations row (to
open new tracked calls) and ohlcv_daily (to resolve already-open ones), so it
runs after recommendation_engine. telegram_alerts reads stock_recommendations
and has no dependency on recommendation_outcomes either way, so it's kept
grouped in this same DAG rather than reordered."""

from airflow import DAG

from _ingestion_docker import DEFAULT_ARGS, START_DATE, ingestion_task

with DAG(
    dag_id="daily_recommendation_ingest",
    description="Recommendation engine recompute + outcome tracking + Telegram push",
    schedule_interval="0 21 * * *",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["domain-8"],
) as dag:
    recommendation_engine = ingestion_task("recommendation_engine", "recommendation_engine")
    recommendation_outcomes = ingestion_task("recommendation_outcomes", "recommendation_outcomes")
    telegram_alerts = ingestion_task("telegram_alerts", "telegram_alerts")

    recommendation_engine >> recommendation_outcomes >> telegram_alerts
