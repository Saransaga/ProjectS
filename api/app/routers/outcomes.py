from fastapi import APIRouter, Depends, HTTPException, Query

from ingestion.query import browse

from ..db import get_conn
from ..dependencies import require_session

router = APIRouter(prefix="/api/outcomes", tags=["outcomes"], dependencies=[Depends(require_session)])

_VALID_ACTIONS = {"STRONG_BUY", "BUY", "SELL", "STRONG_SELL"}
_VALID_STATUSES = {"OPEN", "HIT_TARGET", "HIT_STOP", "EXPIRED"}


@router.get("/summary")
def summary(
    horizon: str = Query("short", pattern="^(short|long)$"),
    actions: list[str] | None = Query(default=None),
) -> dict:
    if actions:
        invalid = [a for a in actions if a not in _VALID_ACTIONS]
        if invalid:
            raise HTTPException(status_code=422, detail=f"Invalid action(s): {invalid}")
    with get_conn() as conn:
        return browse.outcome_summary(conn, horizon=horizon, actions=actions)


@router.get("/open")
def open_positions(
    action: str | None = Query(default=None),
    horizon: str = Query("short", pattern="^(short|long)$"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    if action and action not in _VALID_ACTIONS:
        raise HTTPException(status_code=422, detail=f"Invalid action: {action}")
    with get_conn() as conn:
        rows, total = browse.list_outcomes(
            conn, action=action, status="OPEN", horizon=horizon, limit=limit, offset=offset
        )
    return {"total": total, "items": rows}


@router.get("/by-action")
def by_action(horizon: str = Query("short", pattern="^(short|long)$")) -> dict:
    with get_conn() as conn:
        return {"items": browse.outcome_breakdown_by_action(conn, horizon=horizon)}


@router.get("/by-component")
def by_component(horizon: str = Query("short", pattern="^(short|long)$")) -> dict:
    with get_conn() as conn:
        return {"items": browse.outcome_breakdown_by_component(conn, horizon=horizon)}


@router.get("/{instrument_id}")
def instrument_outcomes(
    instrument_id: int,
    horizon: str = Query("short", pattern="^(short|long)$"),
    status: str | None = Query(default=None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    if status and status not in _VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status: {status}")
    with get_conn() as conn:
        rows, total = browse.list_outcomes(
            conn, instrument_id=instrument_id, status=status, horizon=horizon, limit=limit, offset=offset
        )
    return {"total": total, "items": rows}
