from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request


def build_central_router(
    conn_factory: Callable[[], Any],
    utcnow_fn: Callable[[], datetime],
    parse_dt_fn: Callable[[str | None], datetime | None],
    parse_window_to_minutes_fn: Callable[[str], int],
    normalize_plate_fn: Callable[[str | None], str],
    detect_convoy_groups_fn: Callable[..., list[dict[str, Any]]],
    fetch_alvo_routes_fn: Callable[..., dict[str, Any]],
    compute_threat_center_phase1_fn: Callable[..., dict[str, Any]],
    compute_threat_center_phase2_route_similarity_fn: Callable[..., dict[str, Any]],
    merge_threat_center_phases_fn: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    logger_obj: Any,
) -> APIRouter:
    router = APIRouter(tags=["central"])

    @router.get("/api/central/grupos_suspeitos")
    def central_grupos_suspeitos(
        window: str = "24h",
        co_window: int = 300,
        min_cameras: int = 2,
        max_trip_gap: int = 3600,
        group_sizes: str = "2,3+",
        order_mode: str = "any",
        leader_ratio: float = 0.7,
        payload_max_front: int = 0,
        ts_from: str | None = None,
        ts_to: str | None = None,
        limit: int = 100,
        request: Request = None,
    ):
        window_min = parse_window_to_minutes_fn(window)
        co_win_s = max(1, min(1000, int(co_window)))
        min_cam = max(1, int(min_cameras))
        trip_gap = max(1, int(max_trip_gap))
        lim = max(1, min(500, int(limit)))
        order = str(order_mode).strip().lower()
        if order not in ("any", "leader_front"):
            order = "any"
        lr = max(0.0, min(1.0, float(leader_ratio)))
        p_max_front = max(0, int(payload_max_front))
        if ts_from and ts_to:
            t_from = parse_dt_fn(ts_from) or (utcnow_fn() - timedelta(minutes=window_min))
            t_to = parse_dt_fn(ts_to) or utcnow_fn()
        else:
            t_to = utcnow_fn()
            t_from = t_to - timedelta(minutes=window_min)

        valid_sizes: set[int] = set()
        allow_3plus = False
        for value in str(group_sizes).split(","):
            value = value.strip()
            if value == "2":
                valid_sizes.add(2)
            elif value in ("3+", "3"):
                allow_3plus = True
        if not valid_sizes and not allow_3plus:
            valid_sizes = {2}
            allow_3plus = True

        with conn_factory() as conn:
            with conn.cursor() as cur:
                raw_groups = detect_convoy_groups_fn(
                    cur,
                    t_from,
                    t_to,
                    window_s=co_win_s,
                    max_trip_gap_s=trip_gap,
                    min_cameras=min_cam,
                )
                if allow_3plus:
                    raw_groups = [group for group in raw_groups if group["group_size"] in valid_sizes or group["group_size"] >= 3]
                else:
                    raw_groups = [group for group in raw_groups if group["group_size"] in valid_sizes]

                filtered_groups = []
                for group in raw_groups:
                    cameras_count = group["cameras_count"]
                    plates_set = set(group["plates"])
                    gs = group["group_size"]
                    front_count = Counter()
                    for camera in group["cameras_confirmed"]:
                        if camera.get("plate_order"):
                            front_count[camera["plate_order"][0]] += 1

                    leader_plate = front_count.most_common(1)[0][0] if front_count else group["plates"][0]
                    leader_front_cnt = front_count.get(leader_plate, 0)
                    leader_ratio_val = leader_front_cnt / cameras_count if cameras_count else 0

                    if order == "leader_front":
                        if leader_ratio_val < lr:
                            continue
                        skip = False
                        for plate in plates_set:
                            if plate == leader_plate:
                                continue
                            other_ratio = front_count.get(plate, 0) / cameras_count if cameras_count else 0
                            if other_ratio > 0.3:
                                skip = True
                                break
                        if skip:
                            continue
                        if gs == 3:
                            payload_plate = min(
                                (plate for plate in plates_set if plate != leader_plate),
                                key=lambda plate: front_count.get(plate, 0),
                            )
                            if front_count.get(payload_plate, 0) > p_max_front:
                                continue

                    group["leader"] = leader_plate
                    group["leader_front_count"] = leader_front_cnt
                    group["leader_ratio"] = round(leader_ratio_val, 3)
                    filtered_groups.append(group)

                raw_groups = filtered_groups

                cur.execute("SELECT plate, descricao FROM alvos")
                alvo_map = {row[0]: row[1] for row in cur.fetchall()}

                alvo_routes_cgs = fetch_alvo_routes_fn(
                    cur,
                    list(alvo_map.keys()),
                    t_to - timedelta(days=30),
                    t_to,
                )

                t_from_hist = t_to - timedelta(days=90)
                group_plates_all = set()
                for group in raw_groups:
                    group_plates_all.update(group["plates"])

                days_together_map = {}
                if group_plates_all:
                    placeholders = ",".join(["%s"] * len(group_plates_all))
                    cur.execute(
                        f"""
                        SELECT
                            camera_id,
                            plate,
                            DATE(COALESCE(occurred_at, ts)) AS day
                        FROM lpr_events
                        WHERE plate IN ({placeholders})
                          AND COALESCE(occurred_at, ts) BETWEEN %s AND %s
                    """,
                        list(group_plates_all) + [t_from_hist, t_to],
                    )
                    hist_rows = cur.fetchall()
                    cam_day_plates = {}
                    for cam_id, plate, day in hist_rows:
                        key = (cam_id, str(day))
                        cam_day_plates.setdefault(key, set()).add(plate)

                    for group in raw_groups:
                        plates_set = frozenset(group["plates"])
                        distinct_days = set()
                        for (_, day), plates_present in cam_day_plates.items():
                            if plates_set.issubset(plates_present):
                                distinct_days.add(day)
                        days_together_map[plates_set] = len(distinct_days)

        result = []
        for group in raw_groups:
            plates = group["plates"]
            plates_set = frozenset(plates)
            cams_count = group["cameras_count"]
            trip_sec = group["trip_span_sec"]
            first_seen = group["first_seen"]
            last_seen = group["last_seen"]
            cams_names = list({camera["cam_nome"] for camera in group["cameras_confirmed"]})
            distinct_days = days_together_map.get(plates_set, 0)

            leader = group.get("leader") or plates[0]
            leader_ratio_val = float(group.get("leader_ratio") or 0.0)

            gs = group["group_size"]
            if gs == 2:
                padrao = "BATEDOR" if leader_ratio_val >= 0.70 else "DUPLA"
            elif gs == 3:
                padrao = "COMBOIO 3" if leader_ratio_val >= 0.70 else "GRUPO 3"
            else:
                padrao = f"GRUPO {gs}"

            alvo_norm = {normalize_plate_fn(key): value for key, value in alvo_map.items()}
            alvos_no_grupo = [
                {"plate": plate, "descricao": alvo_norm[normalize_plate_fn(plate)]}
                for plate in plates
                if normalize_plate_fn(plate) in alvo_norm
            ]

            score = 0
            score_reason = []
            if cams_count >= 5:
                score += 40
                score_reason.append(f"{cams_count} câm. em comum (+40)")
            elif cams_count >= 3:
                score += 25
                score_reason.append(f"{cams_count} câm. em comum (+25)")
            else:
                score += 10
                score_reason.append(f"{cams_count} câm. em comum (+10)")

            if distinct_days >= 10:
                score += 35
                score_reason.append(f"{distinct_days} dias distintos (+35)")
            elif distinct_days >= 5:
                score += 25
                score_reason.append(f"{distinct_days} dias distintos (+25)")
            elif distinct_days >= 2:
                score += 15
                score_reason.append(f"{distinct_days} dias distintos (+15)")
            elif distinct_days == 1:
                score += 5
                score_reason.append("1 dia (+5)")

            if padrao == "BATEDOR" and leader_ratio_val >= 0.80:
                score += 20
                score_reason.append("batedor consistente (+20)")
            elif padrao in ("BATEDOR", "COMBOIO 3"):
                score += 10
                score_reason.append("padrão hierárquico (+10)")

            if gs >= 3:
                score += 10
                score_reason.append(f"grupo de {gs} veículos (+10)")

            if alvos_no_grupo:
                bonus = 30 * len(alvos_no_grupo)
                score += bonus
                score_reason.append(f"{len(alvos_no_grupo)} alvo(s) cadastrado(s) (+{bonus})")

            try:
                last_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00")) if last_seen else None
                if last_dt:
                    age_h = (t_to - last_dt).total_seconds() / 3600
                    if age_h <= 2:
                        score += 20
                        score_reason.append("vistos há < 2h (+20)")
                    elif age_h <= 24:
                        score += 10
                        score_reason.append("vistos há < 24h (+10)")
                    elif age_h <= 72:
                        score += 5
                        score_reason.append("vistos há < 72h (+5)")
            except Exception:
                pass

            if cams_count >= 3:
                unique_locs = len(set(cams_names))
                if unique_locs >= 3:
                    score += 10
                    score_reason.append(f"{unique_locs} localidades (+10)")

            risco = "ALTO" if score >= 80 else "MÉDIO" if score >= 40 else "BAIXO"

            threat_center = compute_threat_center_phase1_fn(plates, alvo_map, leader=leader)
            cgs_cam_ids = [camera.get("camera_id", "") for camera in group.get("cameras_confirmed", [])]
            cgs_cities = [camera.get("cam_nome", "") for camera in group.get("cameras_confirmed", [])]
            threat_center_2 = compute_threat_center_phase2_route_similarity_fn(
                cgs_cam_ids,
                cgs_cities,
                alvo_routes_cgs,
            )
            threat_center = merge_threat_center_phases_fn(threat_center, threat_center_2)

            result.append(
                {
                    "id": "_".join(sorted(plates)),
                    "plates": plates,
                    "group_size": gs,
                    "padrao": padrao,
                    "cameras_count": cams_count,
                    "cameras_names": cams_names,
                    "trip_span_sec": trip_sec,
                    "distinct_days": distinct_days,
                    "first_seen": first_seen,
                    "last_seen": last_seen,
                    "leader": leader,
                    "leader_ratio": round(leader_ratio_val, 2),
                    "alvos": alvos_no_grupo,
                    "score": min(score, 200),
                    "score_reason": score_reason,
                    "risco": risco,
                    "cameras_confirmed": group["cameras_confirmed"],
                    "threat_center": threat_center,
                }
            )

        result.sort(key=lambda item: item["score"], reverse=True)
        return {
            "groups": result[:lim],
            "total": len(result),
            "window": window,
            "t_from": t_from.isoformat(),
            "t_to": t_to.isoformat(),
        }

    @router.get("/api/batedor/grupos_comboio")
    def batedor_grupos_comboio(
        window: str = "2h",
        co_window: int = 300,
        group_sizes: str = "2",
        min_cameras: int = 2,
        max_trip_gap: int = 3600,
        order_mode: str = "any",
        leader_ratio: float = 0.7,
        max_front_ratio_other: float = 0.3,
        payload_max_front: int = 0,
        limit: int = 100,
        request: Request = None,
    ):
        allowed_params = {
            "window",
            "co_window",
            "group_sizes",
            "min_cameras",
            "max_trip_gap",
            "order_mode",
            "leader_ratio",
            "max_front_ratio_other",
            "payload_max_front",
            "limit",
        }
        if request:
            unsupported = set(request.query_params.keys()) - allowed_params
            if unsupported:
                raise HTTPException(
                    status_code=400,
                    detail=f"Parâmetros não suportados: {', '.join(sorted(unsupported))}. Use apenas: {', '.join(sorted(allowed_params))}",
                )

        valid_sizes: set[int] = set()
        allow_3plus = False
        for value in str(group_sizes).split(","):
            value = value.strip()
            if value == "2":
                valid_sizes.add(2)
            elif value in ("3+", "3"):
                allow_3plus = True
        if not valid_sizes and not allow_3plus:
            valid_sizes = {2}

        order = str(order_mode).strip().lower()
        if order not in ("any", "leader_front"):
            order = "any"

        lr = max(0.0, min(1.0, float(leader_ratio)))
        mfr_other = max(0.0, min(1.0, float(max_front_ratio_other)))
        p_max_front = max(0, int(payload_max_front))

        window_min = parse_window_to_minutes_fn(window)
        co_win_s = max(1, min(1000, int(co_window)))
        min_cam = max(2, int(min_cameras))
        trip_gap = max(1, int(max_trip_gap))
        lim = max(1, min(500, int(limit)))
        t_to = utcnow_fn()
        t_from = t_to - timedelta(minutes=window_min)

        with conn_factory() as conn:
            with conn.cursor() as cur:
                raw_groups = detect_convoy_groups_fn(
                    cur,
                    t_from,
                    t_to,
                    window_s=co_win_s,
                    max_trip_gap_s=trip_gap,
                    min_cameras=min_cam,
                )

        if allow_3plus:
            raw_groups = [group for group in raw_groups if group["group_size"] in valid_sizes or group["group_size"] >= 3]
        else:
            raw_groups = [group for group in raw_groups if group["group_size"] in valid_sizes]

        groups = []
        for group in raw_groups:
            cameras_confirmed = group["cameras_confirmed"]
            cameras_count = group["cameras_count"]
            plates_set = set(group["plates"])
            gs = group["group_size"]

            front_count = Counter()
            for camera in cameras_confirmed:
                if camera["plate_order"]:
                    front_count[camera["plate_order"][0]] += 1

            leader_plate = front_count.most_common(1)[0][0] if front_count else group["plates"][0]
            leader_front_cnt = front_count.get(leader_plate, 0)
            leader_ratio_val = leader_front_cnt / cameras_count if cameras_count else 0

            if order == "leader_front":
                if leader_ratio_val < lr:
                    continue
                skip = False
                for plate in plates_set:
                    if plate == leader_plate:
                        continue
                    other_ratio = front_count.get(plate, 0) / cameras_count if cameras_count else 0
                    if other_ratio > mfr_other:
                        skip = True
                        break
                if skip:
                    continue
                if gs == 3:
                    payload_plate = min((plate for plate in plates_set if plate != leader_plate), key=lambda plate: front_count.get(plate, 0))
                    if front_count.get(payload_plate, 0) > p_max_front:
                        continue

            roles = {}
            sorted_by_front = sorted(plates_set, key=lambda plate: front_count.get(plate, 0), reverse=True)
            roles[sorted_by_front[0]] = "leader"
            if gs == 2:
                roles[sorted_by_front[1]] = "follower"
            elif gs == 3:
                roles[sorted_by_front[-1]] = "payload"
                mid = [plate for plate in sorted_by_front if plate not in (sorted_by_front[0], sorted_by_front[-1])]
                if mid:
                    roles[mid[0]] = "middle"

            plate_stats = []
            for plate in sorted(plates_set):
                plate_stats.append(
                    {
                        "plate": plate,
                        "front_count": front_count.get(plate, 0),
                        "front_ratio": round(front_count.get(plate, 0) / cameras_count, 3) if cameras_count else 0,
                        "role": roles.get(plate, "member"),
                    }
                )

            group["leader"] = leader_plate
            group["leader_front_count"] = leader_front_cnt
            group["leader_ratio"] = round(leader_ratio_val, 3)
            group["plate_stats"] = plate_stats
            groups.append(group)

        groups.sort(key=lambda group: (group["cameras_count"], group.get("leader_ratio", 0), group["group_size"]), reverse=True)
        sizes_echo = sorted(str(value) for value in valid_sizes)
        if allow_3plus:
            sizes_echo.append("3+")
        return {
            "groups": groups[:lim],
            "total": len(groups),
            "window": window,
            "co_window": co_win_s,
            "group_sizes": sizes_echo,
            "min_cameras": min_cam,
            "max_trip_gap_s": trip_gap,
            "order_mode": order,
            "leader_ratio_threshold": lr,
        }

    @router.get("/api/batedor/central")
    def batedor_central(
        window: str = "2h",
        limit: int = 150,
        ts_from: str | None = None,
        ts_to: str | None = None,
        plate_prefix: str | None = None,
        direcao: str | None = None,
        vehicle_type: str | None = None,
        vehicle_color: str | None = None,
    ):
        logger_obj.info(
            "[batedor_central] window=%s limit=%d ts_from=%s ts_to=%s plate_prefix=%s",
            window,
            limit,
            ts_from,
            ts_to,
            plate_prefix,
        )

        window_min = parse_window_to_minutes_fn(window)
        if ts_from and ts_to:
            t_from = parse_dt_fn(ts_from) or (utcnow_fn() - timedelta(minutes=window_min))
            t_to = parse_dt_fn(ts_to) or utcnow_fn()
        else:
            t_to = utcnow_fn()
            t_from = t_to - timedelta(minutes=window_min)

        def new_item():
            return {
                "in_suspeitos": None,
                "in_comboio": None,
                "in_grupos": [],
                "is_alvo": False,
                "alvo_descricao": None,
                "first_seen": None,
                "last_seen": None,
            }

        intel = defaultdict(new_item)

        def upd(item: dict[str, Any], fs: Any, ls: Any) -> None:
            if fs and (item["first_seen"] is None or fs < item["first_seen"]):
                item["first_seen"] = fs
            if ls and (item["last_seen"] is None or ls > item["last_seen"]):
                item["last_seen"] = ls

        allowed_plates = None
        prefix_sql = ""
        prefix_vals = []
        if plate_prefix:
            prefix_sql = "AND plate ILIKE %s"
            prefix_vals = [plate_prefix.strip().upper() + "%"]

        with conn_factory() as conn:
            with conn.cursor() as cur:
                if direcao or vehicle_type or vehicle_color:
                    ev_conds = ["COALESCE(e.occurred_at, e.ts) BETWEEN %s AND %s"]
                    ev_vals = [t_from, t_to]
                    if direcao:
                        ev_conds.append("UPPER(COALESCE(c.direcao,'')) = UPPER(%s)")
                        ev_vals.append(direcao.strip())
                    if vehicle_type:
                        ev_conds.append("e.yolo_result->'target_vehicle'->>'tipo_raw' = %s")
                        ev_vals.append(vehicle_type.strip())
                    if vehicle_color:
                        ev_conds.append("LOWER(COALESCE(e.yolo_result->'target_vehicle'->>'cor','')) = LOWER(%s)")
                        ev_vals.append(vehicle_color.strip())
                    ev_where = " AND ".join(ev_conds)
                    cur.execute(
                        f"""
                        SELECT DISTINCT e.plate
                        FROM lpr_events e
                        LEFT JOIN cameras c ON c.id = (
                            SELECT id FROM cameras
                            WHERE camera_id = e.camera_id OR ip = e.camera_id
                            ORDER BY (camera_id = e.camera_id) DESC LIMIT 1
                        )
                        WHERE {ev_where}
                          AND e.plate IS NOT NULL
                          AND e.plate NOT IN ('', 'unknown', 'UNKNOWN')
                          {prefix_sql}
                    """,
                        ev_vals + prefix_vals,
                    )
                    allowed_plates = {row[0] for row in cur.fetchall()}

                allow_sql = "AND plate = ANY(%s)" if allowed_plates is not None else ""
                allow_vals = [list(allowed_plates)] if allowed_plates is not None else []

                cur.execute(
                    f"""
                    SELECT plate,
                           COUNT(*)                       AS passes,
                           COUNT(DISTINCT camera_id)      AS cameras,
                           MIN(COALESCE(occurred_at, ts)) AS first_seen,
                           MAX(COALESCE(occurred_at, ts)) AS last_seen
                    FROM lpr_events
                    WHERE plate IS NOT NULL
                      AND plate NOT IN ('', 'unknown', 'UNKNOWN')
                      AND COALESCE(occurred_at, ts) BETWEEN %s AND %s
                      {prefix_sql} {allow_sql}
                    GROUP BY plate
                    HAVING COUNT(*) >= 2 AND COUNT(DISTINCT camera_id) >= 2
                    ORDER BY COUNT(DISTINCT camera_id) DESC, COUNT(*) DESC
                    LIMIT 300
                """,
                    [t_from, t_to] + prefix_vals + allow_vals,
                )
                for row in cur.fetchall():
                    plate = row[0]
                    passes = int(row[1])
                    cameras = int(row[2])
                    fs = row[3]
                    ls = row[4]
                    score = cameras * 10 + passes * 2
                    intel[plate]["in_suspeitos"] = {"score": score, "passes": passes, "cameras": cameras}
                    upd(intel[plate], fs, ls)

                convoy_groups = detect_convoy_groups_fn(
                    cur,
                    t_from,
                    t_to,
                    window_s=300,
                    max_trip_gap_s=3600,
                    min_cameras=2,
                    prefix_sql=prefix_sql,
                    prefix_vals=prefix_vals,
                    allow_sql=allow_sql,
                    allow_vals=allow_vals,
                )
                for group in convoy_groups:
                    cams = group["cameras_count"]
                    score = cams * 15
                    try:
                        fs = datetime.fromisoformat(group["first_seen"]) if isinstance(group["first_seen"], str) else group["first_seen"]
                        ls = datetime.fromisoformat(group["last_seen"]) if isinstance(group["last_seen"], str) else group["last_seen"]
                    except Exception:
                        fs = ls = None
                    for plate in group["plates"]:
                        if not intel[plate]["in_comboio"] or cams > intel[plate]["in_comboio"].get("cameras", 0):
                            intel[plate]["in_comboio"] = {
                                "score": score,
                                "cameras": cams,
                                "trip_span_sec": group["trip_span_sec"],
                            }
                        for other in [value for value in group["plates"] if value != plate]:
                            intel[plate]["in_grupos"].append(
                                {"plate": other, "score": score, "cameras_together": cams}
                            )
                        upd(intel[plate], fs, ls)

                cur.execute(
                    """
                    SELECT DISTINCT ON (plate)
                        plate,
                        yolo_result->'target_vehicle'->>'tipo_raw' AS vtype,
                        yolo_result->'target_vehicle'->>'cor'       AS vcolor
                    FROM lpr_events
                    WHERE plate IS NOT NULL
                      AND COALESCE(occurred_at, ts) BETWEEN %s AND %s
                    ORDER BY plate, COALESCE(occurred_at, ts) DESC
                """,
                    (t_from, t_to),
                )
                for row in cur.fetchall():
                    if row[0] in intel:
                        intel[row[0]]["vehicle_type"] = row[1] or None
                        intel[row[0]]["vehicle_color"] = row[2] or None

                alvo_map = {}
                cur.execute("SELECT plate, descricao FROM alvos")
                for row in cur.fetchall():
                    alvo_map[row[0]] = row[1] or ""
                    item = intel[row[0]]
                    item["is_alvo"] = True
                    item["alvo_descricao"] = row[1] or ""

                plate_cameras = {}
                plate_cities = {}
                if intel:
                    cur.execute(
                        """
                        SELECT e.plate, e.camera_id,
                               COALESCE(c.nome, e.camera_id) AS cam_nome
                        FROM lpr_events e
                        LEFT JOIN cameras c ON c.camera_id = e.camera_id
                        WHERE e.plate = ANY(%s)
                          AND COALESCE(e.occurred_at, e.ts) BETWEEN %s AND %s
                    """,
                        [list(intel.keys()), t_from, t_to],
                    )
                    for plate, cam, nome in cur.fetchall():
                        plate_cameras.setdefault(plate, []).append(cam)
                        plate_cities.setdefault(plate, []).append(nome)

                alvo_routes = fetch_alvo_routes_fn(cur, list(alvo_map.keys()), t_from - timedelta(days=30), t_to)

        items = []
        for plate, item in intel.items():
            companions_count = len(item["in_grupos"])
            sinais = sum(
                [
                    1 if item["in_suspeitos"] else 0,
                    1 if item["in_comboio"] else 0,
                    1 if companions_count else 0,
                    1 if item["is_alvo"] else 0,
                ]
            )
            tc_plates = [plate] + [group["plate"] for group in item["in_grupos"]]
            threat_center = compute_threat_center_phase1_fn(tc_plates, alvo_map, leader=None)
            threat_center_2 = compute_threat_center_phase2_route_similarity_fn(
                group_cameras=plate_cameras.get(plate, []),
                group_cities=plate_cities.get(plate, []),
                alvo_routes=alvo_routes,
            )
            threat_center = merge_threat_center_phases_fn(threat_center, threat_center_2)

            score_activity = int((item["in_suspeitos"] or {}).get("score", 0))
            score_acompanhamento = 0
            if item["in_comboio"]:
                score_acompanhamento += min(int((item["in_comboio"] or {}).get("cameras", 0)), 5) * 4
            if companions_count:
                score_acompanhamento += min(companions_count, 4) * 3
                if companions_count >= 2:
                    score_acompanhamento += 6
            if item["in_suspeitos"] and item["in_comboio"]:
                score_acompanhamento += 10

            route_similarity = (threat_center or {}).get("route_similarity") or {}
            score_rota = 0
            if route_similarity.get("matched"):
                score_rota += 10
            elif float(route_similarity.get("similarity_ratio") or 0) >= 0.5:
                score_rota += 5

            score_alvo = 35 if item["is_alvo"] else 0
            if item["is_alvo"] and companions_count:
                score_alvo += 10

            score_total = int(score_activity + score_acompanhamento + score_rota + score_alvo)
            risk_level = "ALTO" if score_total >= 75 else "MÉDIO" if score_total >= 35 else "BAIXO"

            items.append(
                {
                    "plate": plate,
                    "score_total": score_total,
                    "score_activity": score_activity,
                    "score_acompanhamento": score_acompanhamento,
                    "score_rota": score_rota,
                    "score_alvo": score_alvo,
                    "sinais": sinais,
                    "in_suspeitos": item["in_suspeitos"],
                    "in_comboio": item["in_comboio"],
                    "in_grupos": sorted(item["in_grupos"], key=lambda group: group["cameras_together"], reverse=True)[:5],
                    "companions_count": companions_count,
                    "is_alvo": item["is_alvo"],
                    "alvo_descricao": item["alvo_descricao"],
                    "first_seen": item["first_seen"].isoformat() if item["first_seen"] else None,
                    "last_seen": item["last_seen"].isoformat() if item["last_seen"] else None,
                    "vehicle_type": item.get("vehicle_type"),
                    "vehicle_color": item.get("vehicle_color"),
                    "risk_level": risk_level,
                    "threat_center": threat_center,
                }
            )

        items.sort(key=lambda value: (value["score_total"], value["score_activity"], value["sinais"]), reverse=True)
        logger_obj.info(
            "[batedor_central] resultado: %d itens (total=%d), window retornado=%s",
            len(items[:limit]),
            len(items),
            window,
        )
        return {"items": items[:limit], "total": len(items), "window": window}

    return router
