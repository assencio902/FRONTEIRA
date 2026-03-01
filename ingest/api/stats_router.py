# Camada de API (rota) para estatísticas do sistema
from fastapi import APIRouter
from utils import _conn
from fastapi import HTTPException

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])

@router.get("/overview")
def stats_overview():
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM lpr_events")
            total = int(cur.fetchone()[0])
            cur.execute("""
                SELECT plate, COALESCE(occurred_at, ts)
                FROM lpr_events
                ORDER BY COALESCE(occurred_at, ts) DESC
                LIMIT 1
            """)
            last = cur.fetchone()
            last_plate = last[0] if last else None
            last_ts = last[1].isoformat() if last and last[1] else None
            cur.execute("SELECT COUNT(*) FROM lpr_events WHERE COALESCE(occurred_at, ts) >= %s", (one_hour_ago,))
            last_hour = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM lpr_events WHERE COALESCE(occurred_at, ts) >= %s", (today_start,))
            today_events = int(cur.fetchone()[0])
            cur.execute("""
                SELECT COUNT(DISTINCT camera_id) FROM lpr_events
                WHERE COALESCE(occurred_at, ts) >= %s AND camera_id IS NOT NULL
            """, (now - timedelta(hours=24),))
            active_cameras = int(cur.fetchone()[0])
            cur.execute("""
                SELECT AVG(confidence) FROM (
                    SELECT confidence FROM lpr_events
                    WHERE confidence IS NOT NULL
                    ORDER BY COALESCE(occurred_at, ts) DESC
                    LIMIT 50
                ) t
            """)
            avg_conf = float(cur.fetchone()[0] or 0.0)
    return {
        "total": total,
        "last_plate": last_plate,
        "last_ts": last_ts,
        "last_hour": last_hour,
        "today_events": today_events,
        "active_cameras": active_cameras,
        "avg_confidence": avg_conf,
    }

# Adicione aqui outros endpoints de stats conforme necessário.
