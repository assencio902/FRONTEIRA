# Camada de serviço para eventos LPR
from repositories.event_repository import EventRepository

class EventService:
    @staticmethod
    def list_events(page: int, limit: int, offset: int, plate: str | None, camera_id: str | None, dt_from: str | None, dt_to: str | None):
        items, total = EventRepository.list_events(page, limit, offset, plate, camera_id, dt_from, dt_to)
        return {
            "items": items,
            "page": page,
            "limit": limit,
            "total": total
        }
