from fastapi import APIRouter, Depends

from ingestion.job_cadence import JOB_CADENCE, classify_freshness
from ingestion.query import browse

from ..db import get_conn
from ..dependencies import require_session

router = APIRouter(prefix="/api", tags=["freshness"], dependencies=[Depends(require_session)])


@router.get("/freshness")
def freshness() -> dict:
    """Per-job 'is this up to date' status, judged against each job's own
    expected cadence (ingestion/ingestion/job_cadence.py) rather than one
    global staleness threshold — see that module's docstring."""
    with get_conn() as conn:
        runs = browse.job_latest_runs(conn)

    jobs = []
    for run in runs:
        cadence = JOB_CADENCE.get(run["job_name"])
        jobs.append({
            **run,
            # Judged against the latest *successful* run, not the latest
            # attempt — a job failing on every tick must not read as FRESH
            # just because it keeps trying recently.
            "freshness": classify_freshness(run["job_name"], run["last_success_finished_at"]),
            "cadence": cadence,
        })
    return {"jobs": jobs}
