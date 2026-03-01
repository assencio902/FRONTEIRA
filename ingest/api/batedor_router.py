from fastapi import APIRouter, HTTPException
from utils import _conn, _parse_window_to_minutes, _parse_dt, _utcnow
from datetime import timedelta

router = APIRouter(prefix="/api/v1/batedor", tags=["batedor"])

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
