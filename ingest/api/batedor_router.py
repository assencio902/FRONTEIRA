import math
from collections import defaultdict
from fastapi import APIRouter, HTTPException
from utils import _conn, _parse_window_to_minutes, _parse_dt, _utcnow
from datetime import timedelta

router = APIRouter(prefix="/api/v1/batedor", tags=["batedor"])


# ── Haversine ─────────────────────────────────────────────────────────────────
def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância em km entre dois pontos geográficos (fórmula de Haversine)."""
    R = 6371.0
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    a = (math.sin(dLat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dLon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))

@router.get("/plate/{plate}")
def batedor_plate(plate: str, window_minutes: str = "180", limit: int = 200):
    limit = max(1, min(1000, int(limit)))
    wm = _parse_window_to_minutes(window_minutes)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT e.id, e.plate, e.camera_id, e.channel_name, e.camera_ip, e.confidence,
                       e.image_path, COALESCE(e.occurred_at, e.ts) AS ts, c.direcao, c.nome AS cam_nome
                FROM lpr_events e
                LEFT JOIN cameras c ON c.id = (
                    SELECT id FROM cameras
                    WHERE camera_id = e.camera_id OR ip = e.camera_ip
                    ORDER BY (camera_id = e.camera_id) DESC
                    LIMIT 1
                )
                WHERE e.plate = %s
                  AND COALESCE(e.occurred_at, e.ts) >= NOW() - (%s * INTERVAL '1 minute')
                ORDER BY COALESCE(e.occurred_at, e.ts) DESC
                LIMIT %s
                """,
                (plate, wm, limit),
            )
            rows = cur.fetchall()
    items = []
    for r in rows:
        items.append({
            "id":           r[0],
            "plate":        r[1],
            "camera_id":    r[2],
            "channel_name": r[3],
            "camera_ip":    r[4],
            "confidence":   float(r[5] or 0.0),
            "image_path":   r[6],
            "occurred_at":  r[7].isoformat() if r[7] else None,
            "ts":           r[7].isoformat() if r[7] else None,
            "direcao":      r[8] or None,
            "cam_nome":     r[9] or None,
        })
    return {"items": items}

@router.get("/companions/{plate}")
def batedor_companions(
    plate: str,
    window: str = "24h",
    co_window: int = 600,
    limit: int = 20,
):
    from collections import defaultdict
    co_win_s   = max(10, int(co_window))
    window_min = _parse_window_to_minutes(window)
    lim        = max(1, min(100, int(limit)))
    t_to       = _utcnow()
    t_from     = t_to - timedelta(minutes=window_min)
    plate      = (plate or "").strip()
    if not plate:
        return {"companions": []}
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    b.plate                                              AS companion,
                    a.camera_id                                          AS camera,
                    COALESCE(a.occurred_at, a.ts)                        AS ts_target,
                    COALESCE(b.occurred_at, b.ts)                        AS ts_companion,
                    ABS(EXTRACT(EPOCH FROM (
                        COALESCE(b.occurred_at, b.ts) - COALESCE(a.occurred_at, a.ts)
                    )))::int                                              AS co_delta_sec,
                    COALESCE((a.yolo_result->>'vehicle_count')::int, -1) AS yolo_vc_target,
                    COALESCE((b.yolo_result->>'vehicle_count')::int, -1) AS yolo_vc_companion
                FROM lpr_events a
                JOIN lpr_events b
                    ON  a.camera_id = b.camera_id
                    AND a.id       != b.id
                    AND b.plate    != a.plate
                    AND ABS(EXTRACT(EPOCH FROM (
                            COALESCE(b.occurred_at, b.ts) - COALESCE(a.occurred_at, a.ts)
                        ))) <= %s
                WHERE a.plate = %s
                  AND b.plate IS NOT NULL
                  AND b.plate NOT IN ('', 'unknown', 'UNKNOWN')
                  AND COALESCE(a.occurred_at, a.ts) BETWEEN %s AND %s
                ORDER BY COALESCE(a.occurred_at, a.ts)
                LIMIT 5000
            """, (co_win_s, plate, t_from, t_to))
            rows = cur.fetchall()
    comp_data: dict = defaultdict(lambda: {
        "cameras":           set(),
        "co_deltas":         [],
        "last_seen":         None,
        "companion_leads":   0,
        "target_leads":      0,
        "evidence":          [],
        "yolo_multi_events": 0,
    })
    for row in rows:
        companion, camera, ts_target, ts_companion, co_delta_sec, yolo_vc_t, yolo_vc_c = row
        cd               = comp_data[companion]
        cd["cameras"].add(camera)
        cd["co_deltas"].append(int(co_delta_sec))
        ts_t_iso = ts_target.isoformat()    if ts_target    else None
        ts_c_iso = ts_companion.isoformat() if ts_companion  else None
        if not cd["last_seen"] or (ts_t_iso and ts_t_iso > cd["last_seen"]):
            cd["last_seen"] = ts_t_iso
        if ts_target and ts_companion:
            if ts_companion < ts_target:
                cd["companion_leads"] += 1
            else:
                cd["target_leads"] += 1
        if int(yolo_vc_t) > 1 or int(yolo_vc_c) > 1:
            cd["yolo_multi_events"] += 1
        cd["evidence"].append({
            "camera":            camera,
            "ts_target":         ts_t_iso,
            "ts_companion":      ts_c_iso,
            "co_delta_sec":      int(co_delta_sec),
            "yolo_vc_target":    int(yolo_vc_t),
            "yolo_vc_companion": int(yolo_vc_c),
        })
    result = []
    for companion, cd in comp_data.items():
        ct  = len(cd["cameras"])
        avg = int(sum(cd["co_deltas"]) / len(cd["co_deltas"])) if cd["co_deltas"] else 0
        result.append({
            "companion":         companion,
            "cameras_together":  ct,
            "avg_co_delta_sec":  avg,
            "last_seen":         cd["last_seen"],
            "companion_leads":   cd["companion_leads"],
            "target_leads":      cd["target_leads"],
            "evidence":          cd["evidence"][:20],
            "yolo_multi_events": cd["yolo_multi_events"],
        })
    result.sort(key=lambda x: x["cameras_together"], reverse=True)
    return {"companions": result[:lim]}


# ─────────────────────────────────────────────────────────────────────────────
# TRAJETO — veículos que fizeram o mesmo percurso junto ao alvo
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/trajeto/{plate}")
def batedor_trajeto(
    plate: str,
    window: str = "24h",
    co_window: int = 600,
    min_cameras: int = 2,
    limit: int = 30,
):
    """
    Retorna veículos que transitaram junto ao <plate> no mesmo percurso.

    Para cada companheiro retorna:
    - cameras_together: quantas câmeras percorreram juntos
    - route_distance_km: distância total do percurso (soma das distâncias entre câmeras consecutivas)
    - avg_delta_sec: diferença média de tempo entre eles em cada câmera
    - travel_time_target_sec: tempo que o ALVO levou do início ao fim do percurso
    - travel_time_companion_sec: tempo que o COMPANHEIRO levou do início ao fim do percurso
    - evidence: lista de câmeras com ts de cada um e delta
    """
    co_win_s   = max(10, int(co_window))
    window_min = _parse_window_to_minutes(window)
    min_cam    = max(1, int(min_cameras))
    lim        = max(1, min(200, int(limit)))
    t_to       = _utcnow()
    t_from     = t_to - timedelta(minutes=window_min)
    plate      = (plate or "").strip().upper()
    if not plate:
        raise HTTPException(status_code=400, detail="Placa não informada")

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    b.plate                                              AS companion,
                    a.camera_id                                          AS camera_id,
                    COALESCE(a.occurred_at, a.ts)                        AS ts_target,
                    COALESCE(b.occurred_at, b.ts)                        AS ts_companion,
                    ABS(EXTRACT(EPOCH FROM (
                        COALESCE(b.occurred_at, b.ts) - COALESCE(a.occurred_at, a.ts)
                    )))::int                                              AS delta_sec,
                    c.nome                                               AS cam_nome,
                    c.latitude                                           AS lat,
                    c.longitude                                          AS lon,
                    b.image_path                                         AS companion_image,
                    b.confidence                                         AS companion_confidence
                FROM lpr_events a
                JOIN lpr_events b
                    ON  a.camera_id = b.camera_id
                    AND a.id        != b.id
                    AND b.plate     != a.plate
                    AND b.plate     IS NOT NULL
                    AND b.plate     NOT IN ('', 'unknown', 'UNKNOWN')
                    AND ABS(EXTRACT(EPOCH FROM (
                            COALESCE(b.occurred_at, b.ts) - COALESCE(a.occurred_at, a.ts)
                        ))) <= %s
                LEFT JOIN cameras c
                    ON c.camera_id = a.camera_id
                    OR c.ip        = a.camera_ip
                WHERE a.plate = %s
                  AND COALESCE(a.occurred_at, a.ts) BETWEEN %s AND %s
                ORDER BY COALESCE(a.occurred_at, a.ts) ASC
            """, (co_win_s, plate, t_from, t_to))
            rows = cur.fetchall()

    # ── Agrupamento por companheiro ──────────────────────────────────────────
    comp: dict = defaultdict(lambda: {
        "camera_passages": [],   # lista de dicts ordenada por ts_target
        "last_companion_image": None,
        "last_confidence": 0.0,
    })

    for row in rows:
        companion, camera_id, ts_t, ts_c, delta_sec, cam_nome, lat, lon, img, conf = row
        cd = comp[companion]
        cd["camera_passages"].append({
            "camera_id":    camera_id,
            "cam_nome":     cam_nome or camera_id,
            "ts_target":    ts_t.isoformat() if ts_t else None,
            "ts_companion": ts_c.isoformat() if ts_c else None,
            "delta_sec":    int(delta_sec),
            "lat":          float(lat) if lat is not None else None,
            "lon":          float(lon) if lon is not None else None,
        })
        if img:
            cd["last_companion_image"] = img
        if conf and float(conf) > cd["last_confidence"]:
            cd["last_confidence"] = float(conf)

    # ── Cálculo de métricas por companheiro ──────────────────────────────────
    result = []
    for companion, cd in comp.items():
        passages = cd["camera_passages"]

        # Remove câmeras duplicadas (mantém a de menor delta por câmera)
        seen_cam: dict = {}
        for p in passages:
            cid = p["camera_id"]
            if cid not in seen_cam or p["delta_sec"] < seen_cam[cid]["delta_sec"]:
                seen_cam[cid] = p
        deduped = sorted(seen_cam.values(), key=lambda x: x["ts_target"] or "")

        cameras_together = len(deduped)
        if cameras_together < min_cam:
            continue

        # Distância total do percurso (Haversine entre câmeras consecutivas com coords)
        route_distance_km = 0.0
        points_with_coords = [p for p in deduped if p["lat"] is not None and p["lon"] is not None]
        for i in range(1, len(points_with_coords)):
            p0 = points_with_coords[i - 1]
            p1 = points_with_coords[i]
            route_distance_km += _haversine_km(p0["lat"], p0["lon"], p1["lat"], p1["lon"])

        # Tempo médio de diferença
        deltas = [p["delta_sec"] for p in deduped]
        avg_delta_sec = int(sum(deltas) / len(deltas)) if deltas else 0

        # Tempo total do percurso (alvo)
        ts_list_target = [p["ts_target"] for p in deduped if p["ts_target"]]
        travel_time_target_sec = 0
        if len(ts_list_target) >= 2:
            from datetime import datetime, timezone
            t0 = datetime.fromisoformat(ts_list_target[0])
            t1 = datetime.fromisoformat(ts_list_target[-1])
            travel_time_target_sec = max(0, int((t1 - t0).total_seconds()))

        # Tempo total do percurso (companheiro)
        ts_list_comp = [p["ts_companion"] for p in deduped if p["ts_companion"]]
        travel_time_companion_sec = 0
        if len(ts_list_comp) >= 2:
            from datetime import datetime, timezone
            t0c = datetime.fromisoformat(ts_list_comp[0])
            t1c = datetime.fromisoformat(ts_list_comp[-1])
            travel_time_companion_sec = max(0, int((t1c - t0c).total_seconds()))

        # Score de suspeição: mais câmeras juntas = score maior; empate desfeito por menor delta
        suspicion_score = cameras_together * 100 - avg_delta_sec // 10

        result.append({
            "companion":                 companion,
            "cameras_together":          cameras_together,
            "route_distance_km":         round(route_distance_km, 2),
            "avg_delta_sec":             avg_delta_sec,
            "travel_time_target_sec":    travel_time_target_sec,
            "travel_time_companion_sec": travel_time_companion_sec,
            "suspicion_score":           suspicion_score,
            "last_seen":                 deduped[-1]["ts_target"] if deduped else None,
            "first_seen":                deduped[0]["ts_target"] if deduped else None,
            "last_companion_image":      cd["last_companion_image"],
            "last_confidence":           round(cd["last_confidence"], 3),
            "evidence":                  deduped,
        })

    result.sort(key=lambda x: x["suspicion_score"], reverse=True)
    return {
        "plate":      plate,
        "window":     window,
        "co_window":  co_win_s,
        "companions": result[:lim],
        "total":      len(result),
    }
