import json
import math
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    value = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return radius * 2 * math.asin(math.sqrt(value))


def build_comboio_router(
    conn_factory: Callable[[], Any],
    assert_admin_or_operator_fn: Callable[[Request, str], Any],
    parse_window_to_minutes_fn: Callable[[str], int],
    utcnow_fn: Callable[[], datetime],
    detect_convoy_groups_fn: Callable[..., list[dict[str, Any]]],
    fetch_alvo_routes_fn: Callable[..., dict[str, Any]],
    compute_threat_center_phase1_fn: Callable[..., dict[str, Any]],
    compute_threat_center_phase2_route_similarity_fn: Callable[..., dict[str, Any]],
    merge_threat_center_phases_fn: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
) -> APIRouter:
    router = APIRouter(tags=["comboio"])

    @router.get("/api/batedor/plate/{plate}")
    def batedor_plate(plate: str, window_minutes: str = "180", limit: int = 200):
        limit = max(1, min(1000, int(limit)))
        wm = parse_window_to_minutes_fn(window_minutes)
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT e.id, e.plate, e.camera_id, e.channel_name, e.camera_ip, e.confidence,
                           e.image_path, COALESCE(e.occurred_at, e.ts) AS ts,
                           COALESCE(NULLIF(e.direcao,''), c.direcao) AS direcao,
                           c.nome AS cam_nome
                    FROM lpr_events e
                    LEFT JOIN cameras c ON c.id = (
                        SELECT id FROM cameras
                        WHERE camera_id = e.camera_id OR ip = e.camera_id OR ip = e.camera_ip
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
        for row in rows:
            items.append(
                {
                    "id": row[0],
                    "plate": row[1],
                    "camera_id": row[2],
                    "channel_name": row[3],
                    "camera_ip": row[4],
                    "confidence": float(row[5] or 0.0),
                    "image_path": row[6],
                    "occurred_at": row[7].isoformat() if row[7] else None,
                    "ts": row[7].isoformat() if row[7] else None,
                    "direcao": row[8] or None,
                    "cam_nome": row[9] or None,
                }
            )
        return {"items": items}

    @router.get("/api/batedor/companions/{plate}")
    def batedor_companions(
        plate: str,
        window: str = "24h",
        co_window: int = 300,
        min_cameras: int = 2,
        trip_max: int = 3600,
        limit: int = 20,
    ):
        co_win_s = max(1, min(1000, int(co_window)))
        min_cam = max(1, int(min_cameras))
        trip_max_s = max(1, int(trip_max))
        window_min = parse_window_to_minutes_fn(window)
        lim = max(1, min(100, int(limit)))
        t_to = utcnow_fn()
        t_from = t_to - timedelta(minutes=window_min)
        plate = (plate or "").strip().upper()
        if not plate:
            return {"companions": []}

        with conn_factory() as conn:
            with conn.cursor() as cur:
                groups = detect_convoy_groups_fn(
                    cur,
                    t_from,
                    t_to,
                    window_s=co_win_s,
                    max_trip_gap_s=trip_max_s,
                    min_cameras=min_cam,
                    target_plate=plate,
                    limit_events=12000,
                )
                cur.execute("SELECT plate, descricao FROM alvos")
                alvo_map_raw = {row[0]: row[1] for row in cur.fetchall()}
                alvo_routes_comp = fetch_alvo_routes_fn(
                    cur,
                    list(alvo_map_raw.keys()),
                    t_to - timedelta(days=30),
                    t_to,
                )

        result = []
        for group in groups:
            other_plates = [value for value in group["plates"] if value != plate]
            for companion in other_plates:
                companion_leads = 0
                target_leads = 0
                evidence = []
                for camera in group.get("cameras_confirmed", []):
                    order = camera.get("plate_order", [])
                    if plate in order and companion in order:
                        idx_t = order.index(plate)
                        idx_c = order.index(companion)
                        if idx_c < idx_t:
                            companion_leads += 1
                        elif idx_t < idx_c:
                            target_leads += 1
                    if order and plate in order and companion in order:
                        idx_t = order.index(plate)
                        idx_c = order.index(companion)
                        ts_t = camera.get("ts_min") if idx_t <= idx_c else camera.get("ts_max")
                        ts_c = camera.get("ts_max") if idx_t <= idx_c else camera.get("ts_min")
                    else:
                        ts_t, ts_c = camera.get("ts_min"), camera.get("ts_max")
                    evidence.append(
                        {
                            "camera": camera.get("cam_nome", camera.get("camera_id", "")),
                            "camera_id": camera.get("camera_id", ""),
                            "ts_target": ts_t,
                            "ts_companion": ts_c,
                            "co_delta_sec": camera.get("span_sec", 0),
                            "plate_order": order,
                        }
                    )

                deltas = [item["co_delta_sec"] for item in evidence if item.get("co_delta_sec") is not None]
                front = Counter()
                for camera in group.get("cameras_confirmed", []):
                    order = camera.get("plate_order", [])
                    if order:
                        front[order[0]] += 1
                grp_leader = front.most_common(1)[0][0] if front else None
                grp_plates = [plate, companion]
                threat_center = compute_threat_center_phase1_fn(grp_plates, alvo_map_raw, leader=grp_leader)
                grp_cam_ids = [camera.get("camera_id", "") for camera in group.get("cameras_confirmed", [])]
                grp_cities = [camera.get("cam_nome", "") for camera in group.get("cameras_confirmed", [])]
                threat_center_2 = compute_threat_center_phase2_route_similarity_fn(
                    grp_cam_ids,
                    grp_cities,
                    alvo_routes_comp,
                )
                threat_center = merge_threat_center_phases_fn(threat_center, threat_center_2)

                result.append(
                    {
                        "companion": companion,
                        "cameras_together": group["cameras_count"],
                        "trip_span_sec": group["trip_span_sec"],
                        "min_delta_sec": min(deltas) if deltas else 0,
                        "max_delta_sec": max(deltas) if deltas else 0,
                        "avg_co_delta_sec": int(sum(deltas) / len(deltas)) if deltas else 0,
                        "last_seen": group["last_seen"],
                        "companion_leads": companion_leads,
                        "target_leads": target_leads,
                        "evidence": evidence[:20],
                        "yolo_multi_events": 0,
                        "threat_center": threat_center,
                    }
                )

        result.sort(key=lambda item: item["cameras_together"], reverse=True)
        return {"companions": result[:lim]}

    @router.get("/api/batedor/trajeto/{plate}")
    def batedor_trajeto(
        plate: str,
        window: str = "24h",
        co_window: int = 600,
        min_cameras: int = 2,
        limit: int = 30,
        direcao: str | None = None,
        vehicle_type: str | None = None,
        vehicle_color: str | None = None,
        plate_prefix: str | None = None,
    ):
        from collections import defaultdict

        co_win_s = max(10, int(co_window))
        window_min = parse_window_to_minutes_fn(window)
        min_cam = max(1, int(min_cameras))
        lim = max(1, min(200, int(limit)))
        t_to = utcnow_fn()
        t_from = t_to - timedelta(minutes=window_min)
        plate = (plate or "").strip().upper()
        if not plate:
            raise HTTPException(status_code=400, detail="Placa não informada")

        extra_where = []
        extra_vals = []
        if plate_prefix:
            extra_where.append("AND b.plate ILIKE %s")
            extra_vals.append(plate_prefix.strip().upper() + "%")
        if direcao:
            extra_where.append("AND UPPER(COALESCE(NULLIF(c.direcao,''), '')) = UPPER(%s)")
            extra_vals.append(direcao.strip())
        extra_sql = "\n                  ".join(extra_where)

        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        b.plate                                              AS companion,
                        a.camera_id                                          AS camera_id,
                        COALESCE(a.occurred_at, a.ts)                        AS ts_target,
                        COALESCE(b.occurred_at, b.ts)                        AS ts_companion,
                        ABS(EXTRACT(EPOCH FROM (
                            COALESCE(b.occurred_at, b.ts) - COALESCE(a.occurred_at, a.ts)
                        )))::int                                              AS delta_sec,
                        COALESCE(c.nome, a.camera_id)                        AS cam_nome,
                        c.latitude                                           AS lat,
                        c.longitude                                          AS lon,
                        b.image_path                                         AS companion_image,
                        COALESCE(b.confidence, 0.0)                          AS companion_confidence,
                        COALESCE(
                            NULLIF(b.yolo_result->'target_vehicle'->>'tipo_raw', ''),
                            NULLIF(b.cam_meta->>'vehicle_type', ''),
                            ''
                        )                                                    AS companion_vtype,
                        COALESCE(
                            NULLIF(b.yolo_result->'target_vehicle'->>'cor', ''),
                            ''
                        )                                                    AS companion_color
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
                    LEFT JOIN cameras c ON c.id = (
                        SELECT id FROM cameras
                        WHERE camera_id = a.camera_id
                           OR ip        = a.camera_id
                           OR ip        = a.camera_ip
                        ORDER BY (camera_id = a.camera_id) DESC
                        LIMIT 1
                    )
                    WHERE a.plate = %s
                      AND COALESCE(a.occurred_at, a.ts) BETWEEN %s AND %s
                      {extra_sql}
                    ORDER BY COALESCE(a.occurred_at, a.ts) ASC
                    LIMIT 10000
                """,
                    [co_win_s, plate, t_from, t_to] + extra_vals,
                )
                rows = cur.fetchall()
                cur.execute("SELECT plate, descricao FROM alvos")
                alvo_map_trajeto = {row[0]: row[1] for row in cur.fetchall()}
                alvo_routes_traj = fetch_alvo_routes_fn(
                    cur,
                    list(alvo_map_trajeto.keys()),
                    t_to - timedelta(days=30),
                    t_to,
                )

        comp = defaultdict(
            lambda: {"passages": [], "last_image": None, "max_conf": 0.0, "vtypes": [], "colors": []}
        )
        for row in rows:
            companion, camera_id, ts_t, ts_c, delta_sec, cam_nome, lat, lon, img, conf, vtype, color = row
            item = comp[companion]
            item["passages"].append(
                {
                    "camera_id": camera_id,
                    "cam_nome": cam_nome or camera_id,
                    "ts_target": ts_t.isoformat() if ts_t else None,
                    "ts_companion": ts_c.isoformat() if ts_c else None,
                    "delta_sec": int(delta_sec),
                    "lat": float(lat) if lat is not None else None,
                    "lon": float(lon) if lon is not None else None,
                    "vtype": vtype or None,
                    "color": color or None,
                }
            )
            if img:
                item["last_image"] = img
            if float(conf) > item["max_conf"]:
                item["max_conf"] = float(conf)
            if vtype:
                item["vtypes"].append(vtype.lower())
            if color:
                item["colors"].append(color)

        result = []
        for companion, item in comp.items():
            if vehicle_type:
                vt_clean = vehicle_type.strip().lower()
                if not any(vt_clean in value for value in item["vtypes"]):
                    continue
            if vehicle_color:
                vc_lower = vehicle_color.strip().lower()
                if not any(vc_lower in value.lower() for value in item["colors"]):
                    continue

            best = {}
            for passage in item["passages"]:
                cid = passage["camera_id"]
                if cid not in best or passage["delta_sec"] < best[cid]["delta_sec"]:
                    best[cid] = passage
            deduped = sorted(best.values(), key=lambda value: value["ts_target"] or "")

            cameras_together = len(deduped)
            if cameras_together < min_cam:
                continue

            dominant_vtype = Counter(item["vtypes"]).most_common(1)[0][0] if item["vtypes"] else None
            dominant_color = Counter(item["colors"]).most_common(1)[0][0] if item["colors"] else None

            route_distance_km = 0.0
            pts = [value for value in deduped if value["lat"] is not None and value["lon"] is not None]
            for index in range(1, len(pts)):
                route_distance_km += _haversine_km(
                    pts[index - 1]["lat"],
                    pts[index - 1]["lon"],
                    pts[index]["lat"],
                    pts[index]["lon"],
                )

            deltas = [value["delta_sec"] for value in deduped]
            avg_delta_sec = int(sum(deltas) / len(deltas)) if deltas else 0

            ts_target_list = [value["ts_target"] for value in deduped if value["ts_target"]]
            travel_time_target_sec = 0
            if len(ts_target_list) >= 2:
                t0 = datetime.fromisoformat(ts_target_list[0])
                t1 = datetime.fromisoformat(ts_target_list[-1])
                travel_time_target_sec = max(0, int((t1 - t0).total_seconds()))

            ts_comp_list = [value["ts_companion"] for value in deduped if value["ts_companion"]]
            travel_time_companion_sec = 0
            if len(ts_comp_list) >= 2:
                t0c = datetime.fromisoformat(ts_comp_list[0])
                t1c = datetime.fromisoformat(ts_comp_list[-1])
                travel_time_companion_sec = max(0, int((t1c - t0c).total_seconds()))

            suspicion_score = cameras_together * 100 - avg_delta_sec // 10
            threat_center = compute_threat_center_phase1_fn([plate, companion], alvo_map_trajeto, leader=None)
            traj_cam_ids = [value["camera_id"] for value in deduped]
            traj_cities = [value["cam_nome"] for value in deduped]
            threat_center_2 = compute_threat_center_phase2_route_similarity_fn(
                traj_cam_ids,
                traj_cities,
                alvo_routes_traj,
            )
            threat_center = merge_threat_center_phases_fn(threat_center, threat_center_2)
            suspicion_score += threat_center["score_delta"]

            result.append(
                {
                    "companion": companion,
                    "cameras_together": cameras_together,
                    "route_distance_km": round(route_distance_km, 2),
                    "avg_delta_sec": avg_delta_sec,
                    "travel_time_target_sec": travel_time_target_sec,
                    "travel_time_companion_sec": travel_time_companion_sec,
                    "suspicion_score": suspicion_score,
                    "vehicle_type": dominant_vtype,
                    "vehicle_color": dominant_color,
                    "first_seen": deduped[0]["ts_target"] if deduped else None,
                    "last_seen": deduped[-1]["ts_target"] if deduped else None,
                    "last_companion_image": item["last_image"],
                    "last_confidence": round(item["max_conf"], 3),
                    "evidence": deduped,
                    "threat_center": threat_center,
                }
            )

        result.sort(key=lambda item: item["suspicion_score"], reverse=True)
        return {
            "plate": plate,
            "window": window,
            "co_window": co_win_s,
            "companions": result[:lim],
            "total": len(result),
        }

    @router.get("/api/comboio/report")
    def comboio_report(
        target_plate: str,
        plates: str,
        window: str = "2h",
        window_s: int = 300,
        max_trip_gap_s: int = 3600,
        ts_from: str | None = None,
        ts_to: str | None = None,
    ):
        target_plate = target_plate.strip().upper()
        group_plates = sorted(set(value.strip().upper() for value in plates.split(",") if value.strip()))
        if target_plate not in group_plates:
            group_plates = sorted(set([target_plate] + group_plates))
        if len(group_plates) < 2:
            raise HTTPException(status_code=422, detail="Necessário pelo menos 2 placas")

        window_s = max(1, min(1000, int(window_s)))
        max_trip_gap_s = max(1, int(max_trip_gap_s))

        minutes = parse_window_to_minutes_fn(window)
        t_to = utcnow_fn()
        t_from = t_to - timedelta(minutes=minutes)
        if ts_from:
            try:
                t_from = datetime.fromisoformat(ts_from.replace("Z", "+00:00"))
            except Exception:
                pass
        if ts_to:
            try:
                t_to = datetime.fromisoformat(ts_to.replace("Z", "+00:00"))
            except Exception:
                pass

        with conn_factory() as conn:
            with conn.cursor() as cur:
                convoy = detect_convoy_groups_fn(
                    cur,
                    t_from,
                    t_to,
                    window_s=window_s,
                    max_trip_gap_s=max_trip_gap_s,
                    min_cameras=2,
                    limit_events=15000,
                )
                group_set = frozenset(group_plates)
                matched = None
                for group in convoy:
                    if frozenset(group["plates"]) == group_set:
                        matched = group
                        break
                if not matched:
                    for group in convoy:
                        if target_plate in group["plates"] and set(group["plates"]) <= group_set:
                            matched = group
                            break

                placeholders = ",".join(["%s"] * len(group_plates))
                cur.execute(
                    f"""
                    SELECT e.id, UPPER(e.plate) AS plate, e.camera_id,
                           COALESCE(c.nome, e.channel_name, e.camera_id) AS camera_name,
                           COALESCE(e.occurred_at, e.ts) AS event_time,
                           e.image_path, e.confidence,
                           c.latitude, c.longitude,
                           COALESCE(NULLIF(e.direcao,''), c.direcao) AS direction,
                           COALESCE(e.yolo_result->'target_vehicle'->>'tipo_raw', '') AS vehicle_type,
                           COALESCE(e.yolo_result->'target_vehicle'->>'cor', '') AS vehicle_color
                    FROM lpr_events e
                    LEFT JOIN cameras c ON (
                        c.camera_id = e.camera_id
                        OR c.ip = e.camera_id
                        OR c.ip = e.camera_ip
                    )
                    WHERE UPPER(e.plate) IN ({placeholders})
                      AND COALESCE(e.occurred_at, e.ts) BETWEEN %s AND %s
                    ORDER BY COALESCE(e.occurred_at, e.ts) ASC
                    LIMIT 5000
                """,
                    group_plates + [t_from, t_to],
                )
                all_events = cur.fetchall()

                vehicle_images = {plate_item: None for plate_item in group_plates}
                for row in reversed(all_events):
                    current_plate = row[1]
                    if current_plate in vehicle_images and vehicle_images[current_plate] is None and row[5]:
                        vehicle_images[current_plate] = f"/api/events/{row[0]}/thumbnail"

                from collections import defaultdict as dd

                cam_plate_events = dd(lambda: dd(list))
                for row in all_events:
                    cam_plate_events[row[2]][row[1]].append(row[4])

                confirmed_events = []
                if matched and matched.get("cameras_confirmed"):
                    for camera in matched["cameras_confirmed"]:
                        cam_id = camera["camera_id"]
                        cam_name = camera["cam_nome"]
                        timestamps = {}
                        for plate_item in group_plates:
                            ts_list = cam_plate_events.get(cam_id, {}).get(plate_item, [])
                            if ts_list:
                                cc_min = datetime.fromisoformat(camera["ts_min"]) if isinstance(camera["ts_min"], str) else camera["ts_min"]
                                best_ts = min(ts_list, key=lambda value: abs((value - cc_min).total_seconds()))
                                timestamps[plate_item] = best_ts.isoformat()
                        if len(timestamps) >= 2:
                            ts_vals = [datetime.fromisoformat(value) if isinstance(value, str) else value for value in timestamps.values()]
                            sorted_ts = sorted(ts_vals)
                            delta_s = int((sorted_ts[-1] - sorted_ts[0]).total_seconds())
                            gaps = [(sorted_ts[index + 1] - sorted_ts[index]).total_seconds() for index in range(len(sorted_ts) - 1)]
                            avg_gap = round(sum(gaps) / len(gaps), 1) if gaps else 0
                            confirmed_events.append(
                                {
                                    "camera_id": cam_id,
                                    "camera_name": cam_name,
                                    "timestamps": timestamps,
                                    "delta_s": delta_s,
                                    "avg_gap_s": avg_gap,
                                }
                            )
                else:
                    for cam_id, plate_ts_map in cam_plate_events.items():
                        present = [value for value in group_plates if value in plate_ts_map and plate_ts_map[value]]
                        if len(present) < 2:
                            continue
                        timestamps = {}
                        base_ts = min(plate_ts_map[present[0]])
                        for plate_item in present:
                            best = min(plate_ts_map[plate_item], key=lambda value: abs((value - base_ts).total_seconds()))
                            timestamps[plate_item] = best.isoformat()
                        ts_vals = [datetime.fromisoformat(value) for value in timestamps.values()]
                        sorted_ts = sorted(ts_vals)
                        span = (sorted_ts[-1] - sorted_ts[0]).total_seconds()
                        if span > window_s:
                            continue
                        gaps = [(sorted_ts[index + 1] - sorted_ts[index]).total_seconds() for index in range(len(sorted_ts) - 1)]
                        avg_gap = round(sum(gaps) / len(gaps), 1) if gaps else 0
                        cam_name = None
                        for row in all_events:
                            if row[2] == cam_id:
                                cam_name = row[3]
                                break
                        confirmed_events.append(
                            {
                                "camera_id": cam_id,
                                "camera_name": cam_name or cam_id,
                                "timestamps": timestamps,
                                "delta_s": int(span),
                                "avg_gap_s": avg_gap,
                            }
                        )

                confirmed_events.sort(key=lambda item: min(item["timestamps"].values()))

                total_cameras = len(confirmed_events)
                if confirmed_events:
                    first_ts_vals = [
                        min(datetime.fromisoformat(value) if isinstance(value, str) else value for value in event["timestamps"].values())
                        for event in confirmed_events
                    ]
                    trip_first = min(first_ts_vals)
                    trip_last = max(first_ts_vals)
                    trip_span_s = int((trip_last - trip_first).total_seconds())
                    all_gaps = [event["avg_gap_s"] for event in confirmed_events if event["avg_gap_s"] > 0]
                    avg_gap_overall = round(sum(all_gaps) / len(all_gaps), 1) if all_gaps else 0
                else:
                    trip_span_s = matched["trip_span_sec"] if matched else 0
                    avg_gap_overall = 0

                trip_min = trip_span_s // 60
                trip_sec = trip_span_s % 60
                trip_human = f"{trip_min}m {trip_sec}s" if trip_min else f"{trip_sec}s"

                traj = {plate_item: [] for plate_item in group_plates}
                for row in all_events:
                    current_plate = row[1]
                    if current_plate in traj and row[7] is not None and row[8] is not None:
                        traj[current_plate].append(
                            {
                                "ts": row[4].isoformat(),
                                "camera_id": row[2],
                                "camera_name": row[3],
                                "lat": float(row[7]),
                                "lon": float(row[8]),
                                "direction": row[9],
                                "image_path": row[5],
                                "event_id": row[0],
                            }
                        )

                target_traj = {"plate": target_plate, "points": traj.get(target_plate, [])}
                partner_trajs = [{"plate": value, "points": traj.get(value, [])} for value in group_plates if value != target_plate]

                cur.execute(
                    "SELECT plate FROM alvos WHERE UPPER(plate) IN ({})".format(",".join(["%s"] * len(group_plates))),
                    group_plates,
                )
                alvo_plates = set(row[0].upper() for row in cur.fetchall())

                cur.execute(
                    """
                    SELECT id, decision, decision_note, operator, created_at
                    FROM vehicle_report_decisions
                    WHERE plate = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                """,
                    (target_plate,),
                )
                dec_row = cur.fetchone()
                last_decision = None
                if dec_row:
                    last_decision = {
                        "id": dec_row[0],
                        "decision": dec_row[1],
                        "note": dec_row[2],
                        "operator": dec_row[3],
                        "created_at": dec_row[4].isoformat() if dec_row[4] else None,
                    }

        status = "pending"
        if last_decision:
            status = {"confirmado": "confirmed", "falso_positivo": "false_positive", "ignorar": "pending"}.get(
                last_decision["decision"],
                "pending",
            )

        return {
            "target_plate": target_plate,
            "period": {"start": t_from.isoformat(), "end": t_to.isoformat()},
            "params": {"window_s": window_s, "min_cameras": 2, "max_trip_gap_s": max_trip_gap_s},
            "group": {
                "plates": group_plates,
                "vehicle_images": vehicle_images,
                "status": status,
                "alvos": {value: (value in alvo_plates) for value in group_plates},
            },
            "confirmed_events": confirmed_events,
            "metrics": {
                "total_cameras_confirmed": total_cameras,
                "total_vehicles": len(group_plates),
                "trip_span_s": trip_span_s,
                "trip_span_human": trip_human,
                "avg_gap_overall_s": avg_gap_overall,
            },
            "trajectory": {"target": target_traj, "partners": partner_trajs},
            "last_decision": last_decision,
        }

    @router.post("/api/comboio/confirm", status_code=201)
    async def comboio_confirm(request: Request):
        assert_admin_or_operator_fn(
            request,
            "Apenas administradores e operadores podem confirmar comboio",
        )
        data = await request.json()
        plate = (data.get("target_plate") or "").strip().upper()
        if not plate:
            raise HTTPException(status_code=422, detail="target_plate obrigatório")
        note = str(data.get("note") or "")[:1000]
        group_plates = data.get("group_plates") or []
        params = data.get("params") or {}
        try:
            operator = request.state.user.get("sub", "") if isinstance(request.state.user, dict) else ""
        except Exception:
            operator = ""

        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO vehicle_report_decisions
                        (plate, score_total, level, badges, sinais_principais, decision, decision_note, operator, report_window)
                    VALUES (%s, 0, 'alerta', '["COMBOIO"]'::jsonb, %s::jsonb, 'confirmado', %s, %s, '2h')
                    RETURNING id, created_at
                """,
                    (
                        plate,
                        json.dumps({"comboio": group_plates, "params": params}),
                        note,
                        operator,
                    ),
                )
                row = cur.fetchone()
                desc = note or f"Comboio confirmado - grupo: {', '.join(group_plates)}"
                cur.execute(
                    """
                    INSERT INTO alvos (plate, descricao)
                    VALUES (%s, %s)
                    ON CONFLICT (plate) DO UPDATE SET descricao = EXCLUDED.descricao
                """,
                    (plate, desc),
                )
        return {
            "ok": True,
            "id": row[0],
            "decision": "confirmado",
            "created_at": row[1].isoformat() if row[1] else None,
        }

    @router.post("/api/comboio/false_positive", status_code=201)
    async def comboio_false_positive(request: Request):
        assert_admin_or_operator_fn(
            request,
            "Apenas administradores e operadores podem marcar falso positivo",
        )
        data = await request.json()
        plate = (data.get("target_plate") or "").strip().upper()
        if not plate:
            raise HTTPException(status_code=422, detail="target_plate obrigatório")
        note = str(data.get("note") or "")[:1000]
        group_plates = data.get("group_plates") or []
        params = data.get("params") or {}
        try:
            operator = request.state.user.get("sub", "") if isinstance(request.state.user, dict) else ""
        except Exception:
            operator = ""

        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO vehicle_report_decisions
                        (plate, score_total, level, badges, sinais_principais, decision, decision_note, operator, report_window)
                    VALUES (%s, 0, 'normal', '["COMBOIO"]'::jsonb, %s::jsonb, 'falso_positivo', %s, %s, '2h')
                    RETURNING id, created_at
                """,
                    (
                        plate,
                        json.dumps({"comboio": group_plates, "params": params}),
                        note,
                        operator,
                    ),
                )
                row = cur.fetchone()
        return {
            "ok": True,
            "id": row[0],
            "decision": "falso_positivo",
            "created_at": row[1].isoformat() if row[1] else None,
        }

    return router
