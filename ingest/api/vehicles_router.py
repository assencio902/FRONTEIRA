from typing import Any, Callable

import psycopg2
from fastapi import APIRouter, HTTPException, Request

from rbac import assert_admin_or_operator
from services.fcm_service import normalize_plate
from watchlist_sync import (
    _remove_alvo_from_lista,
    _sync_vehicle_alvo_status,
    _vehicle_has_other_alvo,
)


def build_vehicles_router(conn_factory: Callable[[], Any]) -> APIRouter:
    router = APIRouter(tags=["vehicles"])

    @router.get("/api/vehicles/allplates")
    def vehicles_allplates():
        """Retorna todos os veículos cadastrados agrupados por placa com suas listas."""
        try:
            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT DISTINCT vli.plate, vl.id, vl.name
                        FROM vehicle_list_items vli
                        JOIN vehicle_lists vl ON vl.id = vli.list_id
                        ORDER BY vli.plate
                        """
                    )
                    rows = cur.fetchall()

                    cur.execute(
                        """
                        SELECT al.lista_id, a.prioridade
                        FROM alarme_listas al
                        JOIN alarmes a ON a.id = al.alarme_id
                        WHERE a.ativo = TRUE
                        """
                    )
                    alarm_map = {}
                    for lista_id, prioridade in cur.fetchall():
                        sound = {
                            "critica": "urgent",
                            "alta": "siren",
                            "media": "beep",
                            "baixa": "bell",
                        }.get(prioridade, "beep")
                        prio_order = {"critica": 4, "alta": 3, "media": 2, "baixa": 1}
                        existing = alarm_map.get(lista_id)
                        if not existing or prio_order.get(prioridade, 0) > prio_order.get(existing[0], 0):
                            alarm_map[lista_id] = (prioridade, sound)

            plates = {}
            for plate, list_id, list_name in rows:
                if plate not in plates:
                    plates[plate] = []
                alarm_info = alarm_map.get(list_id)
                plates[plate].append(
                    {
                        "list_id": list_id,
                        "list_name": list_name,
                        "alarm_enabled": alarm_info is not None,
                        "alarm_sound": alarm_info[1] if alarm_info else "beep",
                    }
                )

            return {"plates": plates, "items": list(plates.keys())}
        except Exception as exc:
            return {"plates": {}, "items": [], "error": str(exc)}

    @router.get("/api/vehicles/lists")
    def vehicles_lists():
        try:
            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT vl.id, vl.name,
                               vl.created_at, vl.updated_at,
                               COUNT(vli.id) AS vehicle_count
                        FROM vehicle_lists vl
                        LEFT JOIN vehicle_list_items vli ON vli.list_id = vl.id
                        GROUP BY vl.id
                        ORDER BY vl.updated_at DESC
                        """
                    )
                    rows = cur.fetchall()

            items = []
            for row in rows:
                items.append(
                    {
                        "id": row[0],
                        "name": row[1],
                        "created_at": row[2].isoformat() if row[2] else None,
                        "updated_at": row[3].isoformat() if row[3] else None,
                        "vehicle_count": int(row[4] or 0),
                    }
                )
            return {"items": items}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @router.post("/api/vehicles/lists")
    async def vehicles_lists_create(request: Request):
        assert_admin_or_operator(
            request,
            "Apenas administradores e operadores podem criar listas",
        )
        try:
            data = await request.json()
            name = (data.get("name") or "").strip()
            if not name:
                raise HTTPException(
                    status_code=400,
                    detail="name é obrigatório e não pode ser vazio",
                )

            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO vehicle_lists (name)
                        VALUES (%s)
                        RETURNING id, created_at, updated_at
                        """,
                        (name,),
                    )
                    row = cur.fetchone()

            return {
                "id": row[0],
                "name": name,
                "created_at": row[1].isoformat() if row[1] else None,
                "updated_at": row[2].isoformat() if row[2] else None,
                "vehicle_count": 0,
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @router.put("/api/vehicles/lists/{list_id}")
    async def vehicles_lists_update(list_id: int, request: Request):
        assert_admin_or_operator(
            request,
            "Apenas administradores e operadores podem editar listas",
        )
        try:
            data = await request.json()
            name = (data.get("name") or "").strip()
            if not name:
                raise HTTPException(
                    status_code=400,
                    detail="name é obrigatório e não pode ser vazio",
                )

            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM vehicle_lists WHERE id = %s", (list_id,))
                    if not cur.fetchone():
                        raise HTTPException(status_code=404, detail="Lista não encontrada")

                    cur.execute(
                        """
                        UPDATE vehicle_lists
                        SET name = %s, updated_at = NOW()
                        WHERE id = %s
                        RETURNING id, name, created_at, updated_at
                        """,
                        (name, list_id),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise HTTPException(status_code=404, detail="Lista não encontrada")

            return {
                "id": row[0],
                "name": row[1],
                "created_at": row[2].isoformat() if row[2] else None,
                "updated_at": row[3].isoformat() if row[3] else None,
                "vehicle_count": 0,
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @router.delete("/api/vehicles/lists/{list_id}")
    def vehicles_lists_delete(list_id: int, request: Request):
        assert_admin_or_operator(
            request,
            "Apenas administradores e operadores podem deletar listas",
        )
        try:
            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM vehicle_lists WHERE id = %s", (list_id,))
                    if not cur.fetchone():
                        raise HTTPException(status_code=404, detail="Lista não encontrada")
                    cur.execute("DELETE FROM vehicle_lists WHERE id = %s", (list_id,))
            return {"ok": True}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @router.get("/api/vehicles")
    def vehicles_query(list_id: int | None = None, plate: str | None = None):
        try:
            query = """
                SELECT vli.id, vli.plate, vli.list_id, vl.name AS list_name,
                       vli.notes, vli.created_at, vli.is_alvo
                FROM vehicle_list_items vli
                JOIN vehicle_lists vl ON vl.id = vli.list_id
                WHERE 1=1
            """
            params = []

            if list_id is not None:
                query += " AND vli.list_id = %s"
                params.append(int(list_id))

            if plate and plate.strip():
                query += " AND vli.plate ILIKE %s"
                params.append(f"%{plate.strip()}%")

            query += " ORDER BY vli.created_at DESC LIMIT 1000"

            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    rows = cur.fetchall()

            items = []
            for row in rows:
                items.append(
                    {
                        "id": row[0],
                        "plate": row[1],
                        "list_id": row[2],
                        "list_name": row[3],
                        "notes": row[4],
                        "created_at": row[5].isoformat() if row[5] else None,
                        "is_alvo": bool(row[6]) if row[6] is not None else False,
                    }
                )

            return {"items": items, "total": len(items)}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @router.post("/api/vehicles")
    async def vehicles_create(request: Request):
        assert_admin_or_operator(
            request,
            "Apenas administradores e operadores podem adicionar veículos",
        )
        try:
            data = await request.json()
            plate_raw = data.get("plate")
            if plate_raw is None or plate_raw == "":
                raise HTTPException(status_code=400, detail="plate é obrigatório")
            plate = normalize_plate(str(plate_raw))
            if not plate:
                raise HTTPException(status_code=400, detail="plate não pode ser vazio")

            list_id = data.get("list_id")
            if list_id is None:
                raise HTTPException(status_code=400, detail="list_id é obrigatório")
            if isinstance(list_id, str):
                try:
                    list_id = int(list_id)
                except (ValueError, TypeError):
                    raise HTTPException(status_code=400, detail="list_id deve ser um número")
            elif not isinstance(list_id, int):
                raise HTTPException(status_code=400, detail="list_id deve ser um número")

            notes_raw = data.get("notes")
            notes = None
            if notes_raw:
                notes = str(notes_raw).strip()
                if not notes:
                    notes = None

            is_alvo = bool(data.get("is_alvo", False))

            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM vehicle_lists WHERE id = %s", (list_id,))
                    if not cur.fetchone():
                        raise HTTPException(status_code=404, detail="Lista não encontrada")

                    try:
                        cur.execute(
                            """
                            INSERT INTO vehicle_list_items (list_id, plate, notes, is_alvo)
                            VALUES (%s, %s, %s, %s)
                            RETURNING id, created_at
                            """,
                            (list_id, plate, notes, is_alvo),
                        )
                        row = cur.fetchone()
                        vli_id = row[0]
                        created_at = row[1]
                    except psycopg2.IntegrityError:
                        conn.rollback()
                        raise HTTPException(status_code=409, detail="Placa já existe nesta lista")

                    _sync_vehicle_alvo_status(
                        cur=cur,
                        plate=plate,
                        notes=notes,
                        is_alvo=is_alvo,
                        old_plate=None,
                        old_is_alvo=False,
                        vli_id=vli_id,
                    )

            return {
                "id": vli_id,
                "plate": plate,
                "list_id": list_id,
                "notes": notes,
                "is_alvo": is_alvo,
                "created_at": created_at.isoformat() if created_at else None,
            }
        except HTTPException:
            raise
        except Exception as exc:
            import traceback

            tb = traceback.format_exc()
            raise HTTPException(status_code=500, detail=f"Erro: {str(exc)}. Traceback: {tb}")

    @router.put("/api/vehicles/{vid}")
    async def vehicles_update(vid: int, request: Request):
        assert_admin_or_operator(
            request,
            "Apenas administradores e operadores podem atualizar veículos",
        )
        try:
            data = await request.json()
            plate_raw = data.get("plate")
            notes_raw = data.get("notes")

            plate = None
            if plate_raw is not None:
                plate = normalize_plate(str(plate_raw))
                if not plate:
                    raise HTTPException(status_code=400, detail="plate não pode ser vazio")

            notes = None
            if notes_raw:
                notes = str(notes_raw).strip()
                if not notes:
                    notes = None

            is_alvo_new = data.get("is_alvo")

            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, list_id, plate, notes, is_alvo
                        FROM vehicle_list_items
                        WHERE id = %s
                        """,
                        (vid,),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise HTTPException(status_code=404, detail="Veículo não encontrado")

                    list_id, old_plate, old_notes, old_is_alvo = row[1], row[2], row[3], bool(row[4])
                    effective_plate = plate if plate else old_plate
                    effective_notes = notes if notes_raw is not None else old_notes
                    effective_is_alvo = bool(is_alvo_new) if is_alvo_new is not None else old_is_alvo

                    if plate and plate != old_plate:
                        cur.execute(
                            """
                            SELECT id FROM vehicle_list_items
                            WHERE list_id = %s AND plate = %s AND id != %s
                            """,
                            (list_id, plate, vid),
                        )
                        if cur.fetchone():
                            raise HTTPException(status_code=409, detail="Placa já existe nesta lista")

                    updates = []
                    params = []
                    if plate:
                        updates.append("plate = %s")
                        params.append(plate)
                    if notes_raw is not None:
                        updates.append("notes = %s")
                        params.append(notes)
                    if is_alvo_new is not None:
                        updates.append("is_alvo = %s")
                        params.append(effective_is_alvo)

                    if not updates:
                        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

                    params.append(vid)
                    cur.execute(
                        f"UPDATE vehicle_list_items SET {', '.join(updates)} WHERE id = %s",
                        params,
                    )

                    if is_alvo_new is not None or plate:
                        _sync_vehicle_alvo_status(
                            cur,
                            plate=effective_plate,
                            notes=effective_notes,
                            is_alvo=effective_is_alvo,
                            old_plate=old_plate if plate and plate != old_plate else None,
                            old_is_alvo=old_is_alvo,
                            vli_id=vid,
                        )

            return {"ok": True, "id": vid, "is_alvo": effective_is_alvo}
        except HTTPException:
            raise
        except Exception as exc:
            import traceback

            tb = traceback.format_exc()
            raise HTTPException(status_code=500, detail=f"Erro: {str(exc)}. Traceback: {tb}")

    @router.delete("/api/vehicles/{vid}")
    def vehicles_delete(vid: int, request: Request):
        assert_admin_or_operator(
            request,
            "Apenas administradores e operadores podem deletar veículos",
        )
        try:
            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT plate, is_alvo FROM vehicle_list_items WHERE id = %s",
                        (vid,),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise HTTPException(status_code=404, detail="Veículo não encontrado")

                    plate, was_alvo = row[0], bool(row[1])
                    cur.execute("DELETE FROM vehicle_list_items WHERE id = %s", (vid,))

                    if was_alvo and not _vehicle_has_other_alvo(cur, plate):
                        cur.execute("DELETE FROM alvos WHERE plate = %s", (plate,))
                        _remove_alvo_from_lista(cur, plate)

            return {"ok": True}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    return router
