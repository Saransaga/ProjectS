"""Shared DockerOperator factory used by every DAG in this folder.

Airflow only orchestrates here — it launches a fresh, throwaway container
from the already-built `project-ingestion` image and runs the *existing*
CLI (`python -m ingestion.cli backfill --job <name> --date ...`) inside it.
None of the fetch/parse/upsert logic moves into Airflow; it stays exactly
where it is in ingestion/ingestion/jobs/*.py. This mirrors how the
Streamlit dashboard reuses the same job classes directly rather than going
through a separate API layer (see README.md's Dashboard section) — Airflow
is just another caller of the same CLI scheduler.py already uses.

Not a DAG file itself (defines no DAG object), so Airflow's DAG parser
imports it without creating a spurious empty DAG — this is the standard
"shared helpers alongside DAGs" pattern.
"""

import os
from datetime import datetime, timedelta

from airflow.providers.docker.operators.docker import DockerOperator

# Shared across every DAG: one retry with a 5-minute backoff (a modest
# improvement over scheduler.py's original behavior of just logging the
# exception and moving on with no retry at all — jobs/base.py already logs
# a FAILED row to ingestion_log either way).
DEFAULT_ARGS = {"retries": 1, "retry_delay": timedelta(minutes=5)}
# In the past relative to any real deployment, combined with catchup=False
# below — Airflow only starts scheduling forward from the next tick after
# the DAG is unpaused, it won't try to backfill from this date to now.
START_DATE = datetime(2026, 1, 1)

# docker-compose creates the network as "<project-name>_storage" (the
# `storage` key in docker-compose.yml, prefixed with the compose project
# name — "project" for this repo's default directory-derived project name).
# Override via env if the compose project is ever renamed.
_NETWORK = os.environ.get("INGESTION_DOCKER_NETWORK", "project_storage")
_IMAGE = os.environ.get("INGESTION_IMAGE", "project-ingestion:latest")

# Airflow's default cron semantics trigger a run at the END of its data
# interval — for a daily "0 16 * * *" schedule, the run that fires AT 16:00
# on day D has data_interval [D-1 16:00, D 16:00), so `{{ ds }}` (interval
# start) resolves to D-1, one day behind the date the job should actually
# process. `{{ next_ds }}` (interval end) resolves to D — "today", matching
# scheduler.py's `date.today()` used inside `_run_jobs()`. Every DAG here
# uses next_ds for exactly this reason; using ds instead would silently
# backfill yesterday's date every single run.
_DATE_TEMPLATE = "{{ next_ds }}"


def ingestion_task(task_id: str, job_name: str, **kwargs) -> DockerOperator:
    """One task = one ingestion job (`jobs/*.py`'s `job_name`), run via the
    single-job addressing added to `cli.py` for this migration (`--job
    <job_name>` — see cli.py's `_INDIVIDUAL_JOBS`). The job's own `run()`
    (jobs/base.py) still handles "already succeeded today, skip" /
    "not a trading day, skip" / always_force internally — this wrapper
    doesn't reimplement any of that, same as scheduler.py's `_run_jobs()`
    didn't."""
    return DockerOperator(
        task_id=task_id,
        image=_IMAGE,
        api_version="auto",
        auto_remove="success",
        command=["python", "-m", "ingestion.cli", "backfill", "--job", job_name, "--date", _DATE_TEMPLATE],
        docker_url="unix://var/run/docker.sock",
        network_mode=_NETWORK,
        mount_tmp_dir=False,
        environment={
            "POSTGRES_HOST": os.environ.get("POSTGRES_HOST", "postgres"),
            "POSTGRES_PORT": os.environ.get("POSTGRES_PORT", "5432"),
            "POSTGRES_USER": os.environ["POSTGRES_USER"],
            "POSTGRES_PASSWORD": os.environ["POSTGRES_PASSWORD"],
            "POSTGRES_DB": os.environ["POSTGRES_DB"],
            "REDIS_HOST": os.environ.get("REDIS_HOST", "redis"),
            # Only telegram_alerts.py reads this; every other job ignores it.
            # Forwarded (rather than added ad hoc per-DAG) so a container
            # launched by any DAG behaves the same as one launched by the CLI
            # directly. Empty string (not unset) when absent from .env —
            # config.py's `not config.TELEGRAM_BOT_TOKEN` check treats "" the
            # same as unset.
            "TELEGRAM_BOT_TOKEN": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            "TZ": "Asia/Kolkata",
        },
        **kwargs,
    )
