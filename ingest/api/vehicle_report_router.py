import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request


def build_vehicle_report_router(
    conn_factory: Callable[[], Any],
    assert_admin_or_operator_fn: Callable[[Request, str], Any],
    utcnow_fn: Callable[[], datetime],
    parse_window_to_minutes_fn: Callable[[str], int],
    detect_convoy_groups_fn: Callable[..., list[dict[str, Any]]],
) -> APIRouter:
    router = APIRouter(tags=["vehicle-report"])

    @router.get("/api/vehicle/report")
    def vehicle_report(
        plate: str,
        window: str = "2h",
        ts_from: str | None = None,
        ts_to: str | None = None,
        filter_camera: str | None = None,
        filter_direction: str | None = None,
        min_confidence: float = 0.0,
        min_cameras: int = 0,
        vehicle_type: str | None = None,
        vehicle_color: str | None = None,
        co_window: int = 300,
        limit_events: int = 4000,
        skip_convoy: bool = False,
    ):
        plate = (plate or "").strip().upper()
        if not plate:
            raise HTTPException(status_code=422, detail="plate é obrigatório")

        if ts_from and ts_to:
            try:
                t_from = datetime.fromisoformat(ts_from.replace("Z", "")).replace(tzinfo=timezone.utc)
                t_to = datetime.fromisoformat(ts_to.replace("Z", "")).replace(tzinfo=timezone.utc)
            except Exception:
                window_min = parse_window_to_minutes_fn(window)
                t_to = utcnow_fn()
                t_from = t_to - timedelta(minutes=window_min)
        else:
            window_min = parse_window_to_minutes_fn(window)
            t_to = utcnow_fn()
            t_from = t_to - timedelta(minutes=window_min)

        ev_extra = []
        ev_extra_vals = []
        if filter_camera:
            ev_extra.append("AND e.camera_id = %s")
            ev_extra_vals.append(filter_camera)
        if filter_direction:
            ev_extra.append("AND COALESCE(NULLIF(e.direcao,''), c.direcao) = %s")
            ev_extra_vals.append(filter_direction.upper())
        if min_confidence > 0:
            ev_extra.append("AND COALESCE(e.confidence, 0.0) >= %s")
            ev_extra_vals.append(float(min_confidence))
        if vehicle_type:
            ev_extra.append("AND COALESCE(e.yolo_result->'target_vehicle'->>'tipo_raw', '') ILIKE %s")
            ev_extra_vals.append(vehicle_type)
        if vehicle_color:
            ev_extra.append("AND COALESCE(e.yolo_result->'target_vehicle'->>'cor', '') ILIKE %s")
            ev_extra_vals.append(vehicle_color)
        ev_extra_sql = "\n                  ".join(ev_extra)

        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        e.id,
                        e.plate,
                        e.camera_id,
                        COALESCE(c.nome, e.camera_id)                                AS camera_name,
                        COALESCE(e.occurred_at, e.ts)                                AS ts,
                        e.image_path,
                        COALESCE(NULLIF(e.direcao,''), c.direcao)                    AS direcao,
                        COALESCE((e.yolo_result->>'vehicle_type'), '')               AS vehicle_type,
                        COALESCE((e.yolo_result->>'vehicle_count')::int, 1)          AS vehicle_count,
                        COALESCE(e.confidence, 0.0)                                  AS confidence
                    FROM lpr_events e
                    LEFT JOIN cameras c ON c.id = (
                        SELECT id FROM cameras
                        WHERE camera_id = e.camera_id
                           OR ip        = e.camera_id
                           OR ip        = e.camera_ip
                        ORDER BY (camera_id = e.camera_id) DESC
                        LIMIT 1
                    )
                    WHERE e.plate = %s
                      AND COALESCE(e.occurred_at, e.ts) BETWEEN %s AND %s
                      {ev_extra_sql}
                    ORDER BY ts DESC
                    LIMIT 500
                """,
                    (plate, t_from, t_to, *ev_extra_vals),
                )
                ev_rows = cur.fetchall()

                convoy_groups = []
                if not skip_convoy:
                    co_win_s = max(10, int(co_window))
                    safe_limit = max(500, min(int(limit_events), 20000))
                    convoy_groups = detect_convoy_groups_fn(
                        cur,
                        t_from,
                        t_to,
                        window_s=co_win_s,
                        max_trip_gap_s=3600,
                        min_cameras=2,
                        target_plate=plate,
                        limit_events=safe_limit,
                    )

                partner_data: dict[str, dict[str, Any]] = {}
                for group in convoy_groups:
                    others = [value for value in group["plates"] if value != plate]
                    for other_plate in others:
                        current = partner_data.get(other_plate)
                        if current is None or group["cameras_count"] > current["cameras_together"]:
                            partner_data[other_plate] = {
                                "cameras_together": group["cameras_count"],
                                "cameras_confirmed": [camera["camera_id"] for camera in group["cameras_confirmed"]],
                                "trip_span_sec": group["trip_span_sec"],
                                "first_seen": group["first_seen"],
                                "last_seen": group["last_seen"],
                                "cameras_detail": group["cameras_confirmed"],
                            }

                cur.execute(
                    """
                    SELECT a.plate, a.descricao,
                           vl.name AS list_name
                    FROM alvos a
                    LEFT JOIN vehicle_lists vl ON vl.id = a.list_id
                    WHERE a.plate = %s
                    LIMIT 1
                """,
                    (plate,),
                )
                alvo_row = cur.fetchone()

                partner_plates = list(partner_data.keys())
                alvo_partners: set[str] = set()
                if partner_plates:
                    placeholders = ",".join(["%s"] * len(partner_plates))
                    cur.execute(f"SELECT plate FROM alvos WHERE plate IN ({placeholders})", partner_plates)
                    alvo_partners = {row[0] for row in cur.fetchall()}

                cur.execute(
                    """
                    SELECT id, decision, decision_note, operator, created_at
                    FROM vehicle_report_decisions
                    WHERE plate = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                """,
                    (plate,),
                )
                dec_row = cur.fetchone()

        events = []
        cameras_set: set[str] = set()
        direcoes = []
        confidences = []
        for row in ev_rows:
            cam = str(row[2]) if row[2] else ""
            cameras_set.add(cam)
            direcao = row[6] or ""
            if direcao:
                direcoes.append(direcao)
            confidence = float(row[9]) if row[9] else 0.0
            if confidence > 0:
                confidences.append(confidence)
            events.append(
                {
                    "id": row[0],
                    "plate": row[1],
                    "camera_id": cam,
                    "camera_name": row[3] or cam,
                    "ts": row[4].isoformat() if row[4] else None,
                    "image_path": row[5],
                    "direcao": direcao,
                    "vehicle_type": row[7],
                    "vehicle_count": row[8],
                    "confidence": round(confidence, 2),
                }
            )

        total_passes = len(events)
        cameras_count = len(cameras_set)
        avg_conf = round(sum(confidences) / len(confidences), 2) if confidences else 0.0

        partners = []
        for partner_plate, partner_data_item in partner_data.items():
            partners.append(
                {
                    "plate": partner_plate,
                    "cameras_together": partner_data_item["cameras_together"],
                    "cameras_confirmed": partner_data_item["cameras_confirmed"],
                    "trip_span_sec": partner_data_item["trip_span_sec"],
                    "first_seen": partner_data_item["first_seen"],
                    "last_seen": partner_data_item["last_seen"],
                    "cameras_detail": partner_data_item["cameras_detail"],
                    "is_alvo": partner_plate in alvo_partners,
                }
            )

        partners.sort(key=lambda item: item["cameras_together"], reverse=True)

        if min_cameras > 1:
            partners = [item for item in partners if item["cameras_together"] >= min_cameras]

        is_alvo = alvo_row is not None
        alvo_descricao = alvo_row[1] if alvo_row else None
        alvo_list = alvo_row[2] if alvo_row else None

        breakdown = []
        score = 0

        def add_score(label: str, value: int, multiplier: int, reason: str = "") -> None:
            nonlocal score
            points = value * multiplier
            if points > 0:
                breakdown.append(
                    {
                        "label": label,
                        "value": value,
                        "multiplier": multiplier,
                        "points": points,
                        "reason": reason,
                    }
                )
                score += points

        add_score("Câmeras distintas", cameras_count, 10, "Cada câmera única = +10 pts")
        add_score("Total de passagens", total_passes, 2, "Cada passagem = +2 pts")
        add_score("Parceiros em comboio", len(partners), 15, "Parceiro confirmado (mesma câm ×2+, trip ≤1h) = +15 pts")
        alvo_partners_count = sum(1 for item in partners if item["is_alvo"])
        add_score("Parceiros já cadastrados como alvo", alvo_partners_count, 30, "Parceiro alvo = +30 pts")
        if is_alvo:
            add_score("Placa cadastrada como alvo", 1, 50, "Alvo registrado = +50 pts")

        badges = []
        if is_alvo:
            badges.append("ALVO")
        if cameras_count >= 3:
            badges.append("MULTI-CÂMERA")
        if len(partners) >= 1:
            badges.append("COMBOIO")
        if alvo_partners_count > 0:
            badges.append("PARCEIRO-ALVO")
        if total_passes >= 5:
            badges.append("REINCIDENTE")

        if score >= 80 or is_alvo:
            level = "alerta"
        elif score >= 40:
            level = "suspeito"
        else:
            level = "normal"

        dom_dir = Counter(direcoes).most_common(1)[0][0] if direcoes else None

        last_decision = None
        if dec_row:
            last_decision = {
                "id": dec_row[0],
                "decision": dec_row[1],
                "note": dec_row[2],
                "operator": dec_row[3],
                "created_at": dec_row[4].isoformat() if dec_row[4] else None,
            }

        return {
            "plate": plate,
            "window": window,
            "level": level,
            "is_alvo": is_alvo,
            "alvo_descricao": alvo_descricao,
            "alvo_list": alvo_list,
            "score": score,
            "score_breakdown": breakdown,
            "badges": badges,
            "summary": {
                "total_passes": total_passes,
                "cameras_count": cameras_count,
                "partners_count": len(partners),
                "avg_confidence": avg_conf,
                "first_seen": events[-1]["ts"] if events else None,
                "last_seen": events[0]["ts"] if events else None,
                "dom_direction": dom_dir,
            },
            "events": events,
            "convoy_partners": partners,
            "last_decision": last_decision,
            "filters_applied": {
                "window": window if not (ts_from and ts_to) else None,
                "ts_from": ts_from,
                "ts_to": ts_to,
                "camera": filter_camera,
                "direction": filter_direction,
                "min_confidence": min_confidence if min_confidence > 0 else None,
                "min_cameras": min_cameras if min_cameras > 1 else None,
            },
        }

    @router.post("/api/vehicle/report/decision", status_code=201)
    async def vehicle_report_decision(request: Request):
        assert_admin_or_operator_fn(
            request,
            "Apenas administradores e operadores podem registrar decisões operacionais",
        )
        data = await request.json()
        plate = (data.get("plate") or "").strip().upper()
        decision = (data.get("decision") or "").strip().lower()
        if not plate:
            raise HTTPException(status_code=422, detail="plate é obrigatório")
        allowed = {"confirmado", "falso_positivo", "ignorar"}
        if decision not in allowed:
            raise HTTPException(status_code=422, detail=f"decision deve ser um de: {allowed}")

        score_total = int(data.get("score_total") or 0)
        level = str(data.get("level") or "normal")
        badges = data.get("badges") or []
        sinais = data.get("sinais_principais") or {}
        note = str(data.get("note") or "")[:1000]
        window = str(data.get("window") or "2h")
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
                    VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)
                    RETURNING id, created_at
                """,
                    (
                        plate,
                        score_total,
                        level,
                        json.dumps(badges),
                        json.dumps(sinais),
                        decision,
                        note,
                        operator,
                        window,
                    ),
                )
                row = cur.fetchone()

        return {
            "ok": True,
            "id": row[0],
            "plate": plate,
            "decision": decision,
            "created_at": row[1].isoformat() if row[1] else None,
        }

    @router.get("/api/vehicle/report/decisions")
    def vehicle_report_decisions(
        plate: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ):
        limit = max(1, min(200, int(limit)))
        with conn_factory() as conn:
            with conn.cursor() as cur:
                if plate:
                    plate = plate.strip().upper()
                    cur.execute(
                        """
                        SELECT id, plate, score_total, level, badges, decision,
                               decision_note, operator, report_window, created_at
                        FROM vehicle_report_decisions
                        WHERE plate = %s
                        ORDER BY created_at DESC
                        LIMIT %s OFFSET %s
                    """,
                        (plate, limit, offset),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, plate, score_total, level, badges, decision,
                               decision_note, operator, report_window, created_at
                        FROM vehicle_report_decisions
                        ORDER BY created_at DESC
                        LIMIT %s OFFSET %s
                    """,
                        (limit, offset),
                    )
                rows = cur.fetchall()

        items = []
        for row in rows:
            items.append(
                {
                    "id": row[0],
                    "plate": row[1],
                    "score_total": row[2],
                    "level": row[3],
                    "badges": row[4] if isinstance(row[4], list) else [],
                    "decision": row[5],
                    "note": row[6],
                    "operator": row[7],
                    "window": row[8],
                    "created_at": row[9].isoformat() if row[9] else None,
                }
            )
        return {"items": items, "count": len(items)}

    return router
