import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request

from services.route_similarity_service import calcular_similaridade_rota


def build_trajetoria_router(
    conn_factory: Callable[[], Any],
    require_auth_fn: Callable[[Request], Any],
    detect_convoy_groups_fn: Callable[..., list[dict[str, Any]]],
) -> APIRouter:
    router = APIRouter(tags=["trajetoria"])

    @router.get("/api/vehicles/{plate}/trajectory")
    def vehicle_trajectory(
        plate: str,
        start: str,
        end: str,
        dedupe_seconds: int = 5,
    ):
        plate_raw = plate.strip().upper()
        plate_norm = re.sub(r"[^A-Z0-9]", "", plate_raw)
        if not plate_norm:
            raise HTTPException(status_code=422, detail="plate é obrigatório")

        try:
            dt_start = datetime.fromisoformat(start.replace("Z", "").replace(" ", "T"))
            dt_end = datetime.fromisoformat(end.replace("Z", "").replace(" ", "T"))
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Formato de data inválido: {exc}")

        tz_brt = timezone(timedelta(hours=-3))
        if dt_start.tzinfo is None:
            dt_start = dt_start.replace(tzinfo=tz_brt)
        if dt_end.tzinfo is None:
            dt_end = dt_end.replace(tzinfo=tz_brt)

        dedupe_seconds = max(0, min(60, int(dedupe_seconds)))

        logging.info(
            "[trajectory] plate_raw=%r plate_norm=%r dt_start=%s dt_end=%s",
            plate_raw,
            plate_norm,
            dt_start.isoformat(),
            dt_end.isoformat(),
        )

        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        e.id                                                AS event_id,
                        COALESCE(e.occurred_at, e.ts)                       AS event_time,
                        e.plate,
                        e.camera_id,
                        e.camera_ip,
                        COALESCE(c.nome, e.channel_name, e.camera_id)      AS camera_name,
                        c.latitude,
                        c.longitude,
                        COALESCE(NULLIF(e.direcao,''), c.direcao)           AS direction,
                        COALESCE(e.confidence, 0.0)                         AS confidence,
                        COALESCE(e.yolo_result->'target_vehicle'->>'tipo_raw',
                                 e.cam_meta->>'vehicle_type', '')            AS vehicle_type,
                        COALESCE(e.yolo_result->'target_vehicle'->>'cor', '') AS vehicle_color,
                        e.image_path
                    FROM lpr_events e
                    LEFT JOIN cameras c ON (
                        c.camera_id = e.camera_id
                        OR c.ip = e.camera_id
                        OR c.ip = e.camera_ip
                    )
                    WHERE regexp_replace(upper(coalesce(e.plate,'')), '[^A-Z0-9]', '', 'g')
                          = regexp_replace(upper(%s), '[^A-Z0-9]', '', 'g')
                      AND COALESCE(e.occurred_at, e.ts) BETWEEN %s AND %s
                    ORDER BY COALESCE(e.occurred_at, e.ts) ASC
                    LIMIT 2000
                """,
                    (plate_norm, dt_start, dt_end),
                )
                rows = cur.fetchall()

        logging.info("[trajectory] plate_norm=%r rows_returned=%d", plate_norm, len(rows))

        if not rows:
            return {
                "plate": plate_norm,
                "start": dt_start.isoformat(),
                "end": dt_end.isoformat(),
                "total_events": 0,
                "total_points": 0,
                "cameras_without_gps": [],
                "points": [],
            }

        points = []
        cameras_without_gps = set()
        last_camera_time: dict[str, datetime] = {}

        for row in rows:
            event_id = row[0]
            event_time = row[1]
            cam_id = row[3] or row[4]
            cam_name = row[5]
            lat = row[6]
            lon = row[7]
            direction = row[8]
            confidence = float(row[9] or 0.0)
            vehicle_type = row[10] or None
            vehicle_color = row[11] or None
            image_path = row[12]

            if lat is None or lon is None:
                if cam_name:
                    cameras_without_gps.add(cam_name)
                continue

            if dedupe_seconds > 0 and cam_id:
                last_ts = last_camera_time.get(cam_id)
                if last_ts:
                    delta = (event_time - last_ts).total_seconds()
                    if abs(delta) < dedupe_seconds:
                        continue
                last_camera_time[cam_id] = event_time

            points.append(
                {
                    "event_id": event_id,
                    "ts": event_time.isoformat(),
                    "lat": float(lat),
                    "lon": float(lon),
                    "camera_id": cam_id,
                    "camera_name": cam_name,
                    "direction": direction,
                    "confidence": round(confidence, 2),
                    "vehicle_type": vehicle_type,
                    "vehicle_color": vehicle_color,
                    "image_path": image_path,
                }
            )

        return {
            "plate": plate_norm,
            "start": dt_start.isoformat(),
            "end": dt_end.isoformat(),
            "total_points": len(points),
            "total_events": len(rows),
            "cameras_without_gps": sorted(list(cameras_without_gps)),
            "points": points,
        }

    @router.get("/api/vehicles/{plate}/companions")
    def get_companions(
        plate: str,
        start: str,
        end: str,
        delta_sec: int = 300,
        min_cameras: int = 2,
    ):
        plate = plate.strip().upper()
        if not plate:
            raise HTTPException(status_code=422, detail="plate é obrigatório")

        try:
            dt_start = datetime.fromisoformat(start.replace("Z", "").replace(" ", "T"))
            dt_end = datetime.fromisoformat(end.replace("Z", "").replace(" ", "T"))
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Formato de data inválido: {exc}")

        if dt_start.tzinfo is None:
            dt_start = dt_start.replace(tzinfo=timezone.utc)
        if dt_end.tzinfo is None:
            dt_end = dt_end.replace(tzinfo=timezone.utc)

        delta_sec = max(1, min(1000, int(delta_sec)))
        min_cameras = max(1, min(50, int(min_cameras)))

        with conn_factory() as conn:
            with conn.cursor() as cur:
                groups = detect_convoy_groups_fn(
                    cur,
                    dt_start,
                    dt_end,
                    window_s=delta_sec,
                    max_trip_gap_s=3600,
                    min_cameras=min_cameras,
                    target_plate=plate,
                )

        final_companions = []
        for group in groups:
            other_plates = [value for value in group["plates"] if value != plate]
            for companion in other_plates:
                examples = []
                for camera in group.get("cameras_confirmed", []):
                    examples.append(
                        {
                            "camera_id": camera.get("camera_id", ""),
                            "camera_name": camera.get("cam_nome", camera.get("camera_id", "")),
                            "t_a": camera.get("ts_min"),
                            "t_b": camera.get("ts_max"),
                            "dt_sec": camera.get("span_sec", 0),
                        }
                    )
                final_companions.append(
                    {
                        "companion_plate": companion,
                        "cameras_together": group["cameras_count"],
                        "matches": len(examples),
                        "first_seen": group["first_seen"],
                        "last_seen": group["last_seen"],
                        "trip_span_sec": group["trip_span_sec"],
                        "examples": examples[:5],
                    }
                )

        final_companions.sort(
            key=lambda item: (item["cameras_together"], item["matches"]),
            reverse=True,
        )

        return {
            "plate": plate,
            "period": {"start": dt_start.isoformat(), "end": dt_end.isoformat()},
            "params": {"delta_sec": delta_sec, "min_cameras": min_cameras},
            "total_companions": len(final_companions),
            "companions": final_companions,
        }

    @router.get("/api/rotas/{plate}")
    def rotas_plate(
        plate: str,
        limit: int = 1000,
        dt_from: str | None = None,
        dt_to: str | None = None,
    ):
        plate = (plate or "").strip().upper()
        if not plate:
            raise HTTPException(status_code=400, detail="Placa inválida")
        limit = max(1, min(5000, int(limit)))

        parsed_dt_from = None
        parsed_dt_to = None
        if dt_from:
            try:
                parsed_dt_from = datetime.fromisoformat(dt_from.replace("Z", "+00:00"))
            except ValueError:
                pass
        if dt_to:
            try:
                parsed_dt_to = datetime.fromisoformat(dt_to.replace("Z", "+00:00"))
            except ValueError:
                pass

        date_clause = ""
        date_params: list[Any] = []
        if parsed_dt_from:
            date_clause += " AND COALESCE(e.occurred_at, e.ts) >= %s"
            date_params.append(parsed_dt_from)
        if parsed_dt_to:
            date_clause += " AND COALESCE(e.occurred_at, e.ts) <= %s"
            date_params.append(parsed_dt_to)

        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        e.id,
                        e.plate,
                        COALESCE(c.nome, e.channel_name, e.camera_id) AS camera_name,
                        COALESCE(e.occurred_at, e.ts)                  AS event_time,
                        c.latitude,
                        c.longitude,
                        e.camera_id,
                        COALESCE(c.nome, e.camera_id)                  AS local,
                        e.image_path
                    FROM lpr_events e
                    LEFT JOIN cameras c ON c.id = (
                        SELECT id FROM cameras
                        WHERE camera_id = e.camera_id
                           OR ip = e.camera_id
                           OR ip = e.camera_ip
                        ORDER BY (camera_id = e.camera_id) DESC
                        LIMIT 1
                    )
                    WHERE e.plate = %s{date_clause}
                    ORDER BY COALESCE(e.occurred_at, e.ts) ASC
                    LIMIT %s
                    """,
                    (plate, *date_params, limit),
                )
                rows = cur.fetchall()

        rotas = []
        for seq, row in enumerate(rows, start=1):
            rotas.append(
                {
                    "seq": seq,
                    "plate": row[1],
                    "camera_name": row[2] or "Câmera desconhecida",
                    "event_time": row[3].isoformat() if row[3] else None,
                    "lat": float(row[4]) if row[4] is not None else None,
                    "lon": float(row[5]) if row[5] is not None else None,
                    "camera_id": row[6],
                    "local": row[7] or "Local desconhecido",
                    "image_path": row[8],
                }
            )

        return {"plate": plate, "total": len(rotas), "rotas": rotas}

    @router.post("/api/rotas/similaridade")
    async def rotas_similaridade(request: Request):
        require_auth_fn(request)

        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Body JSON inválido")

        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Body deve ser um objeto JSON")

        eventos_a = body.get("eventos_a")
        eventos_b = body.get("eventos_b")

        if not isinstance(eventos_a, list):
            raise HTTPException(status_code=400, detail="'eventos_a' deve ser uma lista")
        if not isinstance(eventos_b, list):
            raise HTTPException(status_code=400, detail="'eventos_b' deve ser uma lista")

        max_eventos = 5000
        if len(eventos_a) > max_eventos or len(eventos_b) > max_eventos:
            raise HTTPException(
                status_code=400,
                detail=f"Cada lista pode ter no máximo {max_eventos} eventos",
            )

        raw_window = body.get("window_minutes", 30)
        try:
            window_minutes = max(0, min(1440, int(raw_window)))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="'window_minutes' deve ser inteiro")

        return calcular_similaridade_rota(eventos_a, eventos_b, window_minutes)

    return router
