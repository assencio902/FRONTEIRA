from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from utils import _conn, _parse_window_to_minutes, _utcnow
from datetime import timedelta

router = APIRouter(prefix="/api/v1/alvos", tags=["alvos"])

ALVOS_LIST_NAME = "Alvos Rastreados"

def _normalize_plate(value: str | None) -> str:
    raw = (value or "").strip().upper()
    return "".join(ch for ch in raw if ch.isalnum())

def _get_or_create_alvos_list_id(cur) -> int:
    cur.execute("SELECT id FROM vehicle_lists WHERE name = %s", (ALVOS_LIST_NAME,))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE vehicle_lists SET alarm_enabled = TRUE WHERE id = %s", (row[0],))
        return row[0]
    cur.execute(
        """
        INSERT INTO vehicle_lists (name, description, color, alarm_enabled)
        VALUES (%s, %s, %s, TRUE)
        RETURNING id
        """,
        (ALVOS_LIST_NAME, "Gerada automaticamente pelo módulo Batedor/Alvos Rastreados", "#dc2626")
    )
    return cur.fetchone()[0]

def _sync_alvo_to_lista(cur, plate: str, descricao: str, old_plate: str = None):
    plate = _normalize_plate(plate)
    old_plate = _normalize_plate(old_plate) if old_plate else None
    list_id = _get_or_create_alvos_list_id(cur)
    notes = descricao or "Alvo rastreado"
    if old_plate and old_plate != plate:
        cur.execute(
            "DELETE FROM vehicle_list_items WHERE list_id = %s AND plate = %s",
            (list_id, old_plate)
        )
    cur.execute(
        """
        INSERT INTO vehicle_list_items (list_id, plate, notes)
        VALUES (%s, %s, %s)
        ON CONFLICT (list_id, plate) DO UPDATE SET notes = EXCLUDED.notes
        """,
        (list_id, plate, notes)
    )

def _remove_alvo_from_lista(cur, plate: str):
    plate = _normalize_plate(plate)
    cur.execute("SELECT id FROM vehicle_lists WHERE name = %s", (ALVOS_LIST_NAME,))
    row = cur.fetchone()
    if row:
        cur.execute(
            "DELETE FROM vehicle_list_items WHERE list_id = %s AND plate = %s",
            (row[0], plate)
        )

@router.get("/")
def alvos_list():
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, plate, descricao, created_at
                FROM alvos
                ORDER BY created_at DESC
            """)
            rows = cur.fetchall()
    alvos = [
        {"id": r[0], "plate": r[1], "descricao": r[2], "created_at": r[3].isoformat() if r[3] else None}
        for r in rows
    ]
    return {"alvos": alvos, "total": len(alvos)}

@router.post("")
async def alvos_create(request: Request):
    data = await request.json()
    plate = _normalize_plate(data.get("plate") or "")
    descricao = (data.get("descricao") or "").strip()
    if not plate:
        raise HTTPException(status_code=400, detail="Placa obrigatória")
    with _conn() as conn:
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
            r = cur.fetchone()
            _sync_alvo_to_lista(cur, plate, descricao)
    return {"ok": True, "alvo": {"id": r[0], "plate": r[1], "descricao": r[2],
                                  "created_at": r[3].isoformat() if r[3] else None}}

@router.delete("/{aid}")
def alvos_delete(aid: int):
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT plate FROM alvos WHERE id = %s", (aid,))
            row = cur.fetchone()
            if row:
                _remove_alvo_from_lista(cur, row[0])
            cur.execute("DELETE FROM alvos WHERE id = %s", (aid,))
    return {"ok": True}

@router.put("/{aid}")
async def alvos_update(aid: int, request: Request):
    body = await request.json()
    plate    = _normalize_plate(body.get("plate") or "")
    descricao = (body.get("descricao") or "").strip()
    if not plate:
        return JSONResponse(status_code=400, content={"error": "Placa obrigatoria"})
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT plate FROM alvos WHERE id = %s", (aid,))
            row = cur.fetchone()
            if not row:
                return JSONResponse(status_code=404, content={"error": "Alvo nao encontrado"})
            old_plate = row[0]
            cur.execute(
                "UPDATE alvos SET plate = %s, descricao = %s WHERE id = %s RETURNING id, plate, descricao",
                (plate, descricao, aid)
            )
            r = cur.fetchone()
            _sync_alvo_to_lista(cur, plate, descricao, old_plate=old_plate)
    return {"ok": True, "alvo": {"id": r[0], "plate": r[1], "descricao": r[2]}}
