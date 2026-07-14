"""Mirrors scheduler.py's `daily_momentum_ingest` (17:15 IST daily).
fno_signals reads fno_bhavcopy_daily, so it must follow fno_bhavcopy.
deliverable_volume/relative_strength both only need the 16:00 EOD run
(a separate DAG) and have no ordering dependency on the F&O jobs or each
other — same comment as scheduler.py's `_run_daily_momentum_jobs`.

Deliberately excludes fii_dii_flows and bulk_block_deals even though
cli.py's coarser `--job momentum` group bundles them in — those two run on
their own separate schedules below (fii_dii_ingest, bulk_block_deals_poll),
matching scheduler.py's actual production grouping, not cli.py's manual-
backfill-convenience grouping (see docs/PROJECT_STATUS.md)."""

from airflow import DAG

from _ingestion_docker import DEFAULT_ARGS, START_DATE, ingestion_task

with DAG(
    dag_id="daily_momentum_ingest",
    description="F&O bhavcopy/signals + delivery-volume backfill + relative strength",
    schedule_interval="15 17 * * *",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["domain-6"],
) as dag:
    fno_bhavcopy = ingestion_task("fno_bhavcopy", "fno_bhavcopy")
    fno_signals = ingestion_task("fno_signals", "fno_signals")
    deliverable_volume = ingestion_task("deliverable_volume", "deliverable_volume")
    relative_strength = ingestion_task("relative_strength", "relative_strength")

    fno_bhavcopy >> fno_signals
    # deliverable_volume/relative_strength have no upstream dependency in
    # this DAG — they start immediately alongside fno_bhavcopy.
