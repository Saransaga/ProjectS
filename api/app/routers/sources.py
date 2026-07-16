from fastapi import APIRouter, Depends, Query

from ingestion.query import browse

from ..data.roadmap import KNOWN_GAPS
from ..db import get_conn
from ..dependencies import require_session

router = APIRouter(prefix="/api/sources", tags=["sources"], dependencies=[Depends(require_session)])


@router.get("/health")
def health(window_days: int = Query(30, ge=1, le=365)) -> dict:
    with get_conn() as conn:
        return browse.source_health(conn, window_days=window_days)


@router.get("/known-gaps")
def known_gaps() -> dict:
    """Static, hand-curated data sources known to be dead/unverified/blocked
    in this environment — the complement to /health's live volume metrics
    (a source can look "low volume" in /health for a documented reason
    covered here, not just organic disuse)."""
    return {"items": KNOWN_GAPS}
