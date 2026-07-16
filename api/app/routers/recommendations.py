from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from ingestion.query import browse, snapshot
from ingestion.recommendation.price_levels import resolve_price_targets
from ingestion.recommendation.rationale_text import top_reasons

from ..db import get_conn
from ..dependencies import require_session

router = APIRouter(prefix="/api", tags=["recommendations"], dependencies=[Depends(require_session)])

_VALID_ACTIONS = {"STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"}


@router.get("/recommendations")
def list_recommendations(
    horizon: str = Query("short", pattern="^(short|long)$"),
    actions: list[str] | None = Query(default=None),
    as_of_date: date | None = None,
    sort: str = Query("score_desc", pattern="^(score_desc|score_asc|symbol)$"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    if actions:
        invalid = [a for a in actions if a not in _VALID_ACTIONS]
        if invalid:
            raise HTTPException(status_code=422, detail=f"Invalid action(s): {invalid}")

    with get_conn() as conn:
        rows, total, resolved_date = browse.list_recommendations(
            conn, as_of_date=as_of_date, horizon=horizon, actions=actions,
            limit=limit, offset=offset, sort=sort,
        )
    return {"as_of_date": resolved_date, "total": total, "items": rows}


@router.get("/recommendations/{instrument_id}")
def get_recommendation(instrument_id: int) -> dict:
    with get_conn() as conn:
        instrument = browse.get_instrument(conn, instrument_id)
        if instrument is None:
            raise HTTPException(status_code=404, detail="Instrument not found")

        rec = snapshot.latest_recommendation(conn, instrument_id)
        close = snapshot.latest_close(conn, instrument_id)
        levels = snapshot.price_levels(conn, instrument_id, close["close"] if close else None)

    result = {
        "instrument": instrument,
        "close": close,
        "recommendation": None,
    }
    if rec is None:
        return result

    short_targets = resolve_price_targets(rec["short_term_action"], levels)
    result["recommendation"] = {
        **rec,
        "short_term_top_reasons": top_reasons(rec.get("short_term_rationale"), limit=3),
        "long_term_top_reasons": top_reasons(rec.get("long_term_rationale"), limit=3),
        "short_term_price_targets": short_targets,
        "atr_14": levels.get("atr_14") if levels else None,
    }
    return result


@router.get("/movers")
def movers(
    horizon: str = Query("short", pattern="^(short|long)$"),
    direction: str = Query("buy", pattern="^(buy|sell)$"),
    limit: int = Query(5, le=50),
) -> dict:
    with get_conn() as conn:
        as_of_date = snapshot.latest_recommendation_date(conn)
        if as_of_date is None:
            return {"as_of_date": None, "items": []}
        items = snapshot.top_movers(conn, as_of_date, horizon, direction, limit=limit)
    return {"as_of_date": as_of_date, "items": items}


@router.get("/screens/52w-low")
def screen_52_week_low(limit: int = Query(10, le=100)) -> dict:
    with get_conn() as conn:
        return {"items": snapshot.stocks_near_52_week_low(conn, limit=limit)}


@router.get("/screens/dividends")
def screen_dividends(limit: int = Query(10, le=100)) -> dict:
    with get_conn() as conn:
        return {"items": snapshot.top_dividend_yield(conn, limit=limit)}
