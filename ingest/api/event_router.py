# Camada de API (rota) para eventos LPR
from fastapi import APIRouter, Query
from services.event_service import EventService

router = APIRouter(prefix="/api/v1/events", tags=["events"])

@router.get("/")
def list_events(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=200),
    offset: int | None = None,
    plate: str | None = None,
    camera_id: str | None = None,
    dt_from: str | None = None,
    dt_to: str | None = None,
):
    if offset is not None:
        offset = max(0, int(offset))
        page = (offset // limit) + 1
    else:
        page = max(1, int(page))
        offset = (page - 1) * limit
    return EventService.list_events(page, limit, offset, plate, camera_id, dt_from, dt_to)
