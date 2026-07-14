# Airflow orchestration

Replaces `scheduler.py`'s single APScheduler process with 11 Airflow DAGs
(one per cron entry in `scheduler.py` — see
[`docs/PROJECT_STATUS.md`](../docs/PROJECT_STATUS.md)'s schedule table),
giving per-task retries, a Gantt/graph view, and per-run history instead of
only `ingestion_log` rows to inspect.

**Airflow only orchestrates.** Every DAG task launches a fresh, throwaway
container from the already-built `project-ingestion` image and runs the
existing CLI inside it (`python -m ingestion.cli backfill --job <name>
--date ...`) — see `dags/_ingestion_docker.py`. None of the fetch/parse/
upsert logic moved; it's unchanged in `ingestion/ingestion/jobs/*.py`.

## Start

```bash
# One-time: the image's default user (uid 50000) needs to own the log
# volume, and needs the host's docker group to talk to the socket.
sudo mkdir -p /data/airflow-logs /data/airflow-postgres
sudo chown -R 50000:0 /data/airflow-logs
getent group docker   # note the GID (3rd field) — default assumed below is 1001
echo "DOCKER_GID=<that GID>" >> .env   # only if it isn't 1001

docker compose build airflow-init airflow-webserver airflow-scheduler
docker compose up -d airflow-postgres
docker compose up airflow-init          # one-shot: migrates DB, creates admin/admin
docker compose up -d airflow-webserver airflow-scheduler
```

UI at **http://localhost:8080** (`admin` / `admin` — change this before
using anywhere but a local dev box). Every DAG starts **paused**
(`AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION=true` in docker-compose.yml) —
unpause deliberately, per DAG, once you're ready to hand a schedule over
from `scheduler.py` to Airflow, rather than both systems double-ingesting
the same job on day one.

## Two problems hit standing this up, and how they were fixed

Both were caught by actually running a DAG end-to-end (`airflow dags test
<dag_id> <date>`), not just by reading the compose file:

1. **Log volume permission denied.** Docker auto-creates bind-mount host
   directories as `root:root`; the image's default `airflow` user is uid
   50000 and can't write to them. Fixed by pre-creating `/data/airflow-logs`
   and `chown`-ing it to `50000:0` before first boot (see the Start section
   above and the comment in `docker-compose.yml`).
2. **Docker socket permission denied** (`DockerOperator` tasks failed with
   `PermissionError(13, 'Permission denied')` against
   `/var/run/docker.sock`). The socket is group-owned by the host's
   `docker` group, not root, and the container's `airflow` user (gid 0)
   wasn't in it. Fixed with `group_add: ["${DOCKER_GID:-1001}"]` on the
   webserver/scheduler services — set `DOCKER_GID` in `.env` if
   `getent group docker` on your host isn't 1001.

## Why individual jobs, not `cli.py`'s existing `--job` groups

`cli.py`'s groups (`momentum`, `fundamentals`, etc.) are a manual-backfill
convenience and are coarser than `scheduler.py`'s actual production
schedule — e.g. `--job momentum` bundles `fii_dii_flows` and
`bulk_block_deals` in with the F&O jobs, but `scheduler.py` runs those two
on separate schedules for real reasons (see `docs/PROJECT_STATUS.md`). To
replicate `scheduler.py` exactly, `cli.py` gained single-job addressing
(`--job <job_name>`, e.g. `--job fno_bhavcopy`) alongside its existing
groups — see `cli.py`'s `_INDIVIDUAL_JOBS`. Every DAG here calls one job by
name, not a group.

## Why `next_ds`, not `ds`, in every DAG

Airflow's cron scheduling triggers a run at the *end* of its data interval.
For `scheduler.py`'s "fire at 16:00, process today" jobs, that means the
run firing at 16:00 on day D has a data interval of `[D-1 16:00, D 16:00)`
— so `{{ ds }}` (interval start) resolves to **D-1**, one day behind. `{{
next_ds }}` (interval end) resolves to **D**, matching `scheduler.py`'s
`date.today()`. Every DAG's DockerOperator command uses `next_ds` — see
`_ingestion_docker.py`'s docstring. Verified against a real run: a
`monthly_index_rebalancing` test triggered for logical date 2026-07-14
correctly passed `--date 2026-07-01` (the 1st-of-month fire the interval
actually ends on), not 2026-06-01 or 2026-07-14.

## Known behavior deltas from `scheduler.py` (documented, not silent)

- **`announcements_poll`**: `scheduler.py`'s cron fires on the same coarse
  `9-15` hour range this DAG uses, then trims to the real 09:15-15:30
  session with a Python-level `is_market_hours()` check before actually
  fetching. That check lives in the ingestion image, not in Airflow's own
  process, so this DAG doesn't replicate it — the ~09:00-09:14/15:31-15:59
  fringe ticks will call the jobs instead of no-op'ing. Per `scheduler.py`'s
  own comment this was already "a cheap no-op instead of a wasted fetch"
  even in the original design, so this is low-risk, but it is a real,
  intentional difference.
- **Cross-DAG ordering isn't enforced.** E.g. `daily_brokerage_ingest`
  (17:00) trusts that `daily_eod_ingest` (16:00) already produced today's
  close, purely via the wall-clock gap between the two schedules — same as
  `scheduler.py` did (no `ExternalTaskSensor` was added). If a 16:00 run
  runs unusually long, both systems have the same theoretical race; Airflow
  doesn't make this better or worse.

## Cutting over from `scheduler.py`

Both `scheduler.py` (inside the `ingestion` container) and these DAGs can
run at the same time without conflicting — every job's `BaseJob.run()`
checks `ingestion_log` for "already succeeded today" before doing real
work (jobs/base.py), so whichever system gets there first wins and the
other's call becomes a cheap `SKIPPED`. That makes a gradual, DAG-by-DAG
cutover safe: unpause one DAG, watch it succeed for a few days, then
remove its corresponding `scheduler.add_job(...)` call from
`ingestion/ingestion/scheduler.py`. Don't remove `scheduler.py` entirely
until every one of the 11 DAGs has been cut over.
