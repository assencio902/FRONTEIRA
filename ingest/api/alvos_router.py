from datetime import datetime
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request

from rbac import assert_admin, assert_admin_or_operator
from watchlist_sync import _normalize_plate, _remove_alvo_from_lista, _sync_alvo_to_lista


def build_alvos_router(
    conn_factory: Callable[[], Any],
    require_auth_fn: Callable[[Request], dict],
    parse_window_to_minutes_fn: Callable[[str], int],
    parse_dt_fn: Callable[[str | None], datetime | None],
) -> APIRouter:
    router = APIRouter(tags=["alvos"])

    @router.get("/api/alvos")
    def alvos_list():
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT a.id, a.plate, a.descricao, a.created_at,
                           MAX(COALESCE(e.occurred_at, e.ts)) AS last_seen
                    FROM alvos a
                    LEFT JOIN lpr_events e ON e.plate = a.plate
                    GROUP BY a.id, a.plate, a.descricao, a.created_at
                    ORDER BY a.created_at DESC
                    """
                )
                rows = cur.fetchall()
        alvos = [
            {
                "id": row[0],
                "plate": row[1],
                "descricao": row[2],
                "created_at": row[3].isoformat() if row[3] else None,
                "last_seen": row[4].isoformat() if row[4] else None,
            }
            for row in rows
        ]
        return {"alvos": alvos, "total": len(alvos)}

    @router.post("/api/alvos")
    async def alvos_create(request: Request):
        assert_admin_or_operator(request, "Apenas administradores e operadores podem criar alvos")
        data = await request.json()
        plate = _normalize_plate(data.get("plate") or "")
        descricao = (data.get("descricao") or "").strip()
        if not plate:
            raise HTTPException(status_code=400, detail="Placa obrigatória")

        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO alvos (plate, descricao)
                    VALUES (%s, %s)
                    ON CONFLICT (plate) DO UPDATE SET descricao = EXCLUDED.descricao
                    RETURNING id, plate, descricao, created_at
                    """,
                    (plate, descricao),
                )
                row = cur.fetchone()
                _sync_alvo_to_lista(cur, plate, descricao)

        return {
            "ok": True,
            "alvo": {
                "id": row[0],
                "plate": row[1],
                "descricao": row[2],
                "created_at": row[3].isoformat() if row[3] else None,
            },
        }

    @router.delete("/api/alvos/{aid}")
    def alvos_delete(aid: int, request: Request):
        assert_admin(request, "Apenas administradores podem deletar alvos")
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT plate FROM alvos WHERE id = %s", (aid,))
                row = cur.fetchone()
                if row:
                    _remove_alvo_from_lista(cur, row[0])
                cur.execute("DELETE FROM alvos WHERE id = %s", (aid,))
        return {"ok": True}

    @router.put("/api/alvos/{aid}")
    async def alvos_update(aid: int, request: Request):
        assert_admin_or_operator(request, "Apenas administradores e operadores podem editar alvos")
        body = await request.json()
        plate = _normalize_plate(body.get("plate") or "")
        descricao = (body.get("descricao") or "").strip()
        if not plate:
            raise HTTPException(status_code=400, detail="Placa obrigatória")

        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT plate FROM alvos WHERE id = %s", (aid,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Alvo nao encontrado")
                old_plate = row[0]
                cur.execute(
                    """
                    UPDATE alvos
                    SET plate = %s, descricao = %s
                    WHERE id = %s
                    RETURNING id, plate, descricao
                    """,
                    (plate, descricao, aid),
                )
                updated = cur.fetchone()
                _sync_alvo_to_lista(cur, plate, descricao, old_plate=old_plate)

        return {"ok": True, "alvo": {"id": updated[0], "plate": updated[1], "descricao": updated[2]}}

    @router.post("/api/alvos/import-list/{list_id}")
    def alvos_import_list(list_id: int, request: Request):
        assert_admin_or_operator(request, "Apenas administradores e operadores podem importar alvos")
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name FROM vehicle_lists WHERE id = %s", (list_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Lista não encontrada")
                list_name = row[0]
                cur.execute(
                    "SELECT plate, notes FROM vehicle_list_items WHERE list_id = %s",
                    (list_id,),
                )
                items = cur.fetchall()
                if not items:
                    raise HTTPException(status_code=400, detail="Lista não tem veículos cadastrados")
                inserted = 0
                updated = 0
                for plate, notes in items:
                    desc = f"Importado da lista: {list_name}" + (f" — {notes}" if notes else "")
                    cur.execute(
                        """
                        INSERT INTO alvos (plate, descricao)
                        VALUES (%s, %s)
                        ON CONFLICT (plate) DO UPDATE SET descricao = EXCLUDED.descricao
                        """,
                        (_normalize_plate(plate), desc),
                    )
                    if cur.rowcount:
                        inserted += 1
                    else:
                        updated += 1

        return {"ok": True, "list_name": list_name, "total": len(items), "inserted": inserted}

    @router.get("/api/alvos/recentes")
    def alvos_recent(window: str = "30m"):
        wm = parse_window_to_minutes_fn(window)
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT a.id, a.plate, a.descricao, MAX(COALESCE(e.occurred_at, e.ts)) AS ultimo
                    FROM alvos a
                    LEFT JOIN lpr_events e ON e.plate = a.plate
                      AND COALESCE(e.occurred_at, e.ts) >= NOW() - (%s * INTERVAL '1 minute')
                    GROUP BY a.id, a.plate, a.descricao
                    HAVING MAX(COALESCE(e.occurred_at, e.ts)) IS NOT NULL
                    ORDER BY ultimo DESC
                    """,
                    (wm,),
                )
                rows = cur.fetchall()
        return {
            "items": [
                {
                    "id": row[0],
                    "plate": row[1],
                    "descricao": row[2],
                    "ultimo": row[3].isoformat() if row[3] else None,
                }
                for row in rows
            ]
        }

    @router.get("/api/alvos/{aid}")
    def alvo_detalhe(aid: int, request: Request):
        require_auth_fn(request)
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, plate, descricao, created_at FROM alvos WHERE id = %s", (aid,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Alvo não encontrado")
                alvo_id, plate, descricao, created_at = row
                cur.execute(
                    """
                    SELECT COUNT(*), MAX(COALESCE(occurred_at, ts))
                    FROM lpr_events
                    WHERE plate = %s
                    """,
                    (plate,),
                )
                cnt = cur.fetchone()
                total_eventos = int(cnt[0]) if cnt else 0
                ultima_passagem = cnt[1].isoformat() if cnt and cnt[1] else None
                cur.execute("SELECT COUNT(DISTINCT camera_id) FROM lpr_events WHERE plate = %s", (plate,))
                cam_cnt = cur.fetchone()
                total_cameras = int(cam_cnt[0]) if cam_cnt else 0
        return {
            "id": alvo_id,
            "plate": plate,
            "descricao": descricao,
            "created_at": created_at.isoformat() if created_at else None,
            "total_eventos": total_eventos,
            "ultima_passagem": ultima_passagem,
            "total_cameras": total_cameras,
        }

    @router.get("/api/alvos/{aid}/historico")
    def alvo_historico(
        aid: int,
        request: Request,
        range: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        janela_min: Optional[int] = None,
        min_cameras: Optional[int] = None,
        limit: Optional[int] = None,
    ):
        require_auth_fn(request)
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT plate FROM alvos WHERE id = %s", (aid,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Alvo não encontrado")
                plate = row[0]

        where: list[str] = ["e.plate = %s"]
        vals: list[Any] = [plate]

        range_map = {"24h": 24 * 60, "7d": 7 * 1440, "15d": 15 * 1440, "30d": 30 * 1440}
        if range and range in range_map:
            mins = range_map[range]
            where.append(f"COALESCE(e.occurred_at, e.ts) >= NOW() - ({mins} * INTERVAL '1 minute')")
        else:
            dt_from = parse_dt_fn(start)
            if dt_from:
                where.append("COALESCE(e.occurred_at, e.ts) >= %s")
                vals.append(dt_from)
            t_raw = (end + "T23:59:59") if end and "T" not in end else end
            dt_to = parse_dt_fn(t_raw)
            if dt_to:
                where.append("COALESCE(e.occurred_at, e.ts) <= %s")
                vals.append(dt_to)

        wsql = "WHERE " + " AND ".join(where)

        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT e.id, e.plate, e.camera_id, e.channel_name, e.camera_ip, e.confidence,
                           e.image_path, COALESCE(e.occurred_at, e.ts) AS when_ts,
                           c.nome AS cam_nome,
                           COALESCE(NULLIF(e.direcao,''), c.direcao) AS direcao
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
                    LIMIT %s
                    """,
                    tuple(vals) + ((limit if limit and limit > 0 else 500),),
                )
                rows = cur.fetchall()

        events: list[dict] = []
        cameras_vistas: set = set()
        for row in rows:
            ts = row[7].isoformat() if row[7] else None
            cam_id = row[2] or ""
            cameras_vistas.add(cam_id)
            events.append(
                {
                    "id": row[0],
                    "plate": row[1],
                    "camera_id": cam_id,
                    "channel_name": row[3],
                    "camera_ip": row[4],
                    "confidence": float(row[5] or 0.0),
                    "image_path": row[6],
                    "occurred_at": ts,
                    "camera": row[8] or row[3] or cam_id,
                    "direcao": row[9] or "",
                }
            )

        if janela_min and janela_min > 0 and min_cameras and min_cameras > 1:
            from datetime import timedelta as _td

            janela = _td(minutes=janela_min)
            filtered: list[dict] = []
            for ev in events:
                if not ev["occurred_at"]:
                    continue
                t0 = datetime.fromisoformat(ev["occurred_at"])
                cams_in_window: set = set()
                for ev2 in events:
                    if not ev2["occurred_at"]:
                        continue
                    t2 = datetime.fromisoformat(ev2["occurred_at"])
                    if abs((t2 - t0).total_seconds()) <= janela.total_seconds():
                        cams_in_window.add(ev2["camera_id"])
                if len(cams_in_window) >= min_cameras:
                    filtered.append(ev)
            events = filtered
        elif min_cameras and min_cameras > 1:
            all_cams = {ev["camera_id"] for ev in events}
            if len(all_cams) < min_cameras:
                events = []

        return {
            "plate": plate,
            "total": len(events),
            "cameras_count": len(cameras_vistas),
            "events": events,
        }

    return router
