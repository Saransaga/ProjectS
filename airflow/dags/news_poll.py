"""Mirrors scheduler.py's `news_poll` (every 30 min, every day of the
week — RSS/Reddit don't stop at market close or on weekends). Both jobs
set always_force=True (jobs/base.py), so no trading-day gating applies
either in the original or here."""

from airflow import DAG

from _ingestion_docker import DEFAULT_ARGS, START_DATE, ingestion_task

with DAG(
    dag_id="news_poll",
    description="RSS financial news + Reddit sentiment",
    schedule_interval="*/30 * * * *",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["domain-4"],
) as dag:
    ingestion_task("rss_news", "rss_news")
    ingestion_task("reddit_sentiment", "reddit_sentiment")
