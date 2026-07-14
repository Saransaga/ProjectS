"""Mirrors scheduler.py's `daily_recommendation_ingest` (21:00 IST daily).
recommendation_engine recomputes from the day's technicals/momentum/
brokerage/fundamentals tables (all landed by 19:00 at the latest across the
other DAGs, trusted to the wall-clock gap same as every other cross-DAG
dependency in this project — see daily_brokerage_ingest.py's docstring).
telegram_alerts reads stock_recommendations, so it runs after
recommendation_engine in this same DAG."""

from airflow import DAG

from _ingestion_docker import DEFAULT_ARGS, START_DATE, ingestion_task

with DAG(
    dag_id="daily_recommendation_ingest",
    description="Recommendation engine recompute + Telegram push",
    schedule_interval="0 21 * * *",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["domain-8"],
) as dag:
    recommendation_engine = ingestion_task("recommendation_engine", "recommendation_engine")
    telegram_alerts = ingestion_task("telegram_alerts", "telegram_alerts")

    recommendation_engine >> telegram_alerts
