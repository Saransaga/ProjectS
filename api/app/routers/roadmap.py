from fastapi import APIRouter, Depends

from ..data.roadmap import ROADMAP
from ..dependencies import require_session

router = APIRouter(prefix="/api", tags=["roadmap"], dependencies=[Depends(require_session)])


@router.get("/roadmap")
def roadmap() -> dict:
    return {"items": ROADMAP}
