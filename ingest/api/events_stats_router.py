import json
from datetime import datetime, timedelta
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from starlette.responses import RedirectResponse


def build_events_stats_router(
    conn_factory: Callable[[], Any],
    parse_dt_fn: Callable[[str | None], datetime | None],
    utcnow_fn: Callable[[], datetime],
    get_event_by_id_fn: Callable[[int], dict[str, Any] | None],
) -> APIRouter:
    router = APIRouter(tags=["events-stats"])

    def _normalize_image_url(value: str | None) -> str | None:
        if not value:
            return None
        value = str(value).strip()
        if not value:
            return None
        if value.startswith(("http://", "https://", "/")):
            return value
        return f"/uploads/{value.lstrip('./')}"

    @router.get("/api/events")
    def list_events(
        page: int = 1,
        limit: int = 10,
        offset: int | None = None,
        plate: str | None = None,
        camera_id: str | None = None,
        dt_from: str | None = None,
        dt_to: str | None = None,
    ):
        limit = max(1, min(200, int(limit)))
        if offset is not None:
            offset = max(0, int(offset))
            page = (offset // limit) + 1
        else:
            page = max(1, int(page))
            offset = (page - 1) * limit

        where = []
        vals: list[Any] = []
        if plate:
            where.append("e.plate ILIKE %s")
            vals.append(f"%{plate.strip()}%")
        if camera_id:
            cid = camera_id.strip()
            where.append("(e.camera_id = %s OR e.camera_ip = %s OR e.camera_id IN (SELECT camera_id FROM cameras WHERE ip = %s))")
            vals.extend([cid, cid, cid])

        f = parse_dt_fn(dt_from)
        t = parse_dt_fn(dt_to)
        if f:
            where.append("COALESCE(e.occurred_at, e.ts) >= %s")
            vals.append(f)
        if t:
            where.append("COALESCE(e.occurred_at, e.ts) <= %s")
            vals.append(t)

        wsql = ("WHERE " + " AND ".join(where)) if where else ""

        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM lpr_events e {wsql}", tuple(vals))
                total = int(cur.fetchone()[0])
                cur.execute(
                    f"""
                    SELECT e.id, e.plate, e.camera_id, e.channel_name, e.camera_ip, e.confidence,
                           e.image_path, COALESCE(e.occurred_at, e.ts) AS when_ts, e.yolo_result,
                           c.nome AS cam_nome,
                           COALESCE(NULLIF(e.direcao,''), c.direcao) AS direcao,
                           e.cam_meta
                    FROM lpr_events e
                    LEFT JOIN cameras c ON c.id = (
                        SELECT id FROM cameras
                        WHERE camera_id = e.camera_id
                           OR ip        = e.camera_id
                           OR ip        = e.camera_ip
                        ORDER BY (camera_id = e.camera_id) DESC
                        LIMIT 1
                    )
                    {wsql}
                    ORDER BY COALESCE(e.occurred_at, e.ts) DESC
                    LIMIT %s OFFSET %s
                    """,
                    tuple(vals + [limit, offset]),
                )
                rows = cur.fetchall()

        items = []
        for row in rows:
            ts = row[7].isoformat() if row[7] else None
            img = _normalize_image_url(row[6])
            raw_yolo = row[8]
            if raw_yolo is None:
                yolo = None
            elif isinstance(raw_yolo, dict):
                yolo = raw_yolo
            else:
                yolo = json.loads(raw_yolo)
            items.append(
                {
                    "id": row[0],
                    "plate": row[1],
                    "camera_id": row[2],
                    "channel_name": row[3],
                    "camera_ip": row[4],
                    "confidence": float(row[5] or 0.0),
                    "image_path": img,
                    "occurred_at": ts,
                    "camera": row[9] or row[3],
                    "timestamp": ts,
                    "image": img,
                    "thumb": img,
                    "yolo_result": yolo,
                    "sem_placa_motivo": yolo.get("sem_placa_motivo") if yolo else None,
                    "vehicle_details": yolo.get("vehicle_details") if yolo else None,
                    "target_vehicle": yolo.get("target_vehicle") if yolo else None,
                    "image_quality": yolo.get("image_quality") if yolo else None,
                    "cam_nome": row[9] or row[3],
                    "direcao": row[10] or None,
                    "cam_meta": (json.loads(row[11]) if isinstance(row[11], str) else row[11]) if row[11] else None,
                }
            )

        return {"items": items, "page": page, "limit": limit, "total": total}

    @router.get("/api/events/{event_id}")
    def get_event_detail(event_id: int):
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT e.id, e.plate, e.camera_id, e.channel_name, e.camera_ip, e.confidence,
                           e.image_path, COALESCE(e.occurred_at, e.ts) AS when_ts, e.yolo_result,
                           c.nome AS cam_nome,
                           COALESCE(NULLIF(e.direcao,''), c.direcao) AS direcao,
                           e.cam_meta
                    FROM lpr_events e
                    LEFT JOIN cameras c ON c.id = (
                        SELECT id FROM cameras
                        WHERE camera_id = e.camera_id
                           OR ip        = e.camera_id
                           OR ip        = e.camera_ip
                        ORDER BY (camera_id = e.camera_id) DESC
                        LIMIT 1
                    )
                    WHERE e.id = %s
                    LIMIT 1
                    """,
                    (event_id,),
                )
                row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="evento nao encontrado")

        ts = row[7].isoformat() if row[7] else None
        raw_yolo = row[8]
        if raw_yolo is None:
            yolo = None
        elif isinstance(raw_yolo, dict):
            yolo = raw_yolo
        else:
            yolo = json.loads(raw_yolo)

        image_url = _normalize_image_url(row[6])
        return {
            "id": row[0],
            "plate": row[1],
            "camera_id": row[2],
            "channel_name": row[3],
            "camera_ip": row[4],
            "confidence": float(row[5] or 0.0),
            "image_path": image_url,
            "occurred_at": ts,
            "camera": row[9] or row[3],
            "timestamp": ts,
            "image": image_url,
            "thumb": image_url,
            "yolo_result": yolo,
            "sem_placa_motivo": yolo.get("sem_placa_motivo") if yolo else None,
            "vehicle_details": yolo.get("vehicle_details") if yolo else None,
            "target_vehicle": yolo.get("target_vehicle") if yolo else None,
            "image_quality": yolo.get("image_quality") if yolo else None,
            "cam_nome": row[9] or row[3],
            "direcao": row[10] or None,
            "cam_meta": (json.loads(row[11]) if isinstance(row[11], str) else row[11]) if row[11] else None,
        }

    @router.get("/api/events/{event_id}/image")
    def get_event_image(event_id: int):
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT image_path FROM lpr_events WHERE id=%s LIMIT 1", (event_id,))
                row = cur.fetchone()
        image_url = _normalize_image_url(row[0] if row else None)
        if not image_url:
            raise HTTPException(status_code=404, detail="imagem nao encontrada")
        return RedirectResponse(url=image_url)

    @router.get("/api/events/{event_id}/thumbnail")
    def api_event_thumbnail(event_id: int, w: int = 144, h: int = 96):
        event = get_event_by_id_fn(event_id)
        if not event:
            raise HTTPException(status_code=404, detail="evento nao encontrado")
        thumb = _normalize_image_url(event.get("thumb") or event.get("image") or event.get("image_path"))
        if not thumb:
            raise HTTPException(status_code=404, detail="imagem nao disponivel para este evento")
        return RedirectResponse(url=thumb, status_code=302)

    @router.get("/api/stats/overview")
    def stats_overview():
        now = utcnow_fn()
        one_hour_ago = now - timedelta(hours=1)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM lpr_events")
                total = int(cur.fetchone()[0])
                cur.execute(
                    """
                    SELECT plate, COALESCE(occurred_at, ts)
                    FROM lpr_events
                    ORDER BY COALESCE(occurred_at, ts) DESC
                    LIMIT 1
                """
                )
                last = cur.fetchone()
                last_plate = last[0] if last else None
                last_ts = last[1].isoformat() if last and last[1] else None
                cur.execute("SELECT COUNT(*) FROM lpr_events WHERE COALESCE(occurred_at, ts) >= %s", (one_hour_ago,))
                last_hour = int(cur.fetchone()[0])
                cur.execute("SELECT COUNT(*) FROM lpr_events WHERE COALESCE(occurred_at, ts) >= %s", (today_start,))
                today_events = int(cur.fetchone()[0])
                cur.execute(
                    """
                    SELECT COUNT(DISTINCT camera_id) FROM lpr_events
                    WHERE COALESCE(occurred_at, ts) >= %s
                      AND camera_id IS NOT NULL
                """,
                    (now - timedelta(hours=24),),
                )
                active_cameras = int(cur.fetchone()[0])
                cur.execute(
                    """
                    SELECT AVG(confidence) FROM (
                        SELECT confidence FROM lpr_events
                        WHERE confidence IS NOT NULL
                        ORDER BY COALESCE(occurred_at, ts) DESC
                        LIMIT 50
                    ) t
                """
                )
                avg_conf = cur.fetchone()[0]
                avg_conf = float(avg_conf) if avg_conf is not None else 0.0

        avg_conf_val = round(avg_conf * 100, 1) if avg_conf <= 1.0 else round(avg_conf, 1)
        return {
            "total": total,
            "total_db": total,
            "total_events": total,
            "today_events": today_events,
            "last_plate": last_plate,
            "last_ts": last_ts,
            "last_hour": last_hour,
            "last_hour_count": last_hour,
            "last_hour_events": last_hour,
            "active_cameras": active_cameras,
            "monitored_plates": 0,
            "alerts_today": 0,
            "alerts": 0,
            "avg_confidence_last_50": avg_conf_val,
            "avg_conf_last50": avg_conf_val,
        }

    @router.get("/api/stats/events-per-hour")
    def stats_events_per_hour(hours: int = 12):
        hours = max(1, min(72, int(hours)))
        now = utcnow_fn()
        start = now - timedelta(hours=hours)
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT date_trunc('hour', COALESCE(occurred_at, ts)) AS h, COUNT(*)
                    FROM lpr_events
                    WHERE COALESCE(occurred_at, ts) >= %s
                    GROUP BY 1
                    ORDER BY 1 ASC
                """,
                    (start,),
                )
                rows = cur.fetchall()
        items = [{"hour": row[0].strftime("%H:00"), "count": int(row[1])} for row in rows]
        return {"items": items, "labels": [row["hour"] for row in items], "values": [row["count"] for row in items]}

    @router.get("/api/stats/events-per-day")
    def stats_events_per_day(days: int = 30):
        days = max(1, min(365, int(days)))
        now = utcnow_fn()
        start = now - timedelta(days=days)
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT date_trunc('day', COALESCE(occurred_at, ts)) AS d, COUNT(*)
                    FROM lpr_events
                    WHERE COALESCE(occurred_at, ts) >= %s
                    GROUP BY 1
                    ORDER BY 1 ASC
                """,
                    (start,),
                )
                rows = cur.fetchall()
        items = [{"day": row[0].date().isoformat(), "count": int(row[1])} for row in rows]
        return {"items": items, "labels": [row["day"] for row in items], "values": [row["count"] for row in items]}

    @router.get("/api/stats/top-plates")
    def stats_top_plates(limit: int = 10):
        limit = max(1, min(50, int(limit)))
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT plate, COUNT(*) as c
                    FROM lpr_events
                    WHERE plate IS NOT NULL AND plate <> ''
                    GROUP BY plate
                    ORDER BY c DESC
                    LIMIT %s
                """,
                    (limit,),
                )
                rows = cur.fetchall()
        return {"items": [{"plate": row[0], "count": int(row[1])} for row in rows]}

    @router.get("/api/stats/events-per-camera")
    def stats_events_per_camera():
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COALESCE(channel_name, camera_id, 'desconhecida') as cam, COUNT(*) as c
                    FROM lpr_events
                    GROUP BY 1
                    ORDER BY c DESC
                    LIMIT 50
                """
                )
                rows = cur.fetchall()
        return {"items": [{"camera": row[0], "count": int(row[1])} for row in rows[:10]]}

    return router
