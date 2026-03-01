# Camada de API (rota) para veículos
from fastapi import APIRouter, Request, HTTPException
from utils import _conn
import psycopg2

router = APIRouter(prefix="/api/v1/vehicles", tags=["vehicles"])

@router.get("/allplates")
def vehicles_allplates():
    """Retorna todos os veículos cadastrados agrupados por placa com suas listas."""
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT vli.plate, vl.id, vl.name, vl.color
                    FROM vehicle_list_items vli
                    JOIN vehicle_lists vl ON vl.id = vli.list_id
                    ORDER BY vli.plate
                """)
                rows = cur.fetchall()
        plates = {}
        for plate, list_id, list_name, color in rows:
            if plate not in plates:
                plates[plate] = []
            plates[plate].append({
                "list_id": list_id,
                "list_name": list_name,
                "color": color
            })
        return {"plates": plates, "items": list(plates.keys())}
    except Exception as e:
        return {"plates": {}, "items": [], "error": str(e)}

@router.get("/lists")
def vehicles_lists():
    """Retorna lista de todas as listas com contagem de veículos."""
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT vl.id, vl.name, vl.description, vl.color, vl.alarm_enabled, \
                           vl.alarm_sound, vl.created_at, vl.updated_at,
                           COUNT(vli.id) as vehicle_count
                    FROM vehicle_lists vl
                    LEFT JOIN vehicle_list_items vli ON vli.list_id = vl.id
                    GROUP BY vl.id
                    ORDER BY vl.updated_at DESC
                """)
                rows = cur.fetchall()
        items = []
        for r in rows:
            items.append({
                "id": r[0],
                "name": r[1],
                "description": r[2],
                "color": r[3],
                "alarm_enabled": r[4],
                "alarm_sound": r[5],
                "created_at": r[6].isoformat() if r[6] else None,
                "updated_at": r[7].isoformat() if r[7] else None,
                "vehicle_count": int(r[8] or 0)
            })
        return {"items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/lists")
async def vehicles_lists_create(request: Request):
    """Cria uma nova lista de monitoramento."""
    try:
        data = await request.json()
        name = (data.get("name") or "").strip()
        description = (data.get("description") or "").strip()
        color = data.get("color") or "#000000"
        alarm_enabled = data.get("alarm_enabled", False)
        alarm_sound = data.get("alarm_sound")
        if not name:
            raise HTTPException(status_code=400, detail="name é obrigatório e não pode ser vazio")
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO vehicle_lists (name, description, color, alarm_enabled, alarm_sound)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, created_at, updated_at
                """, (name, description if description else None, color, alarm_enabled, alarm_sound))
                r = cur.fetchone()
        return {
            "id": r[0],
            "name": name,
            "description": description if description else None,
            "color": color,
            "alarm_enabled": alarm_enabled,
            "alarm_sound": alarm_sound,
            "created_at": r[1].isoformat() if r[1] else None,
            "updated_at": r[2].isoformat() if r[2] else None,
            "vehicle_count": 0
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/lists/{list_id}")
async def vehicles_lists_update(list_id: int, request: Request):
    """Edita uma lista de monitoramento."""
    try:
        data = await request.json()
        name = (data.get("name") or "").strip()
        description = (data.get("description") or "").strip()
        color = data.get("color") or "#000000"
        alarm_enabled = data.get("alarm_enabled", False)
        alarm_sound = data.get("alarm_sound")
        if not name:
            raise HTTPException(status_code=400, detail="name é obrigatório e não pode ser vazio")
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM vehicle_lists WHERE id = %s", (list_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Lista não encontrada")
                cur.execute("""
                    UPDATE vehicle_lists
                    SET name = %s, description = %s, color = %s, alarm_enabled = %s, \
                        alarm_sound = %s, updated_at = NOW()
                    WHERE id = %s
                    RETURNING id, name, description, color, alarm_enabled, alarm_sound, created_at, updated_at
                """, (name, description if description else None, color, alarm_enabled, alarm_sound, list_id))
                r = cur.fetchone()
                if not r:
                    raise HTTPException(status_code=404, detail="Lista não encontrada")
        return {
            "id": r[0],
            "name": r[1],
            "description": r[2],
            "color": r[3],
            "alarm_enabled": r[4],
            "alarm_sound": r[5],
            "created_at": r[6].isoformat() if r[6] else None,
            "updated_at": r[7].isoformat() if r[7] else None,
            "vehicle_count": 0
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/lists/{list_id}")
def vehicles_lists_delete(list_id: int):
    """Deleta uma lista e todos seus veículos."""
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM vehicle_lists WHERE id = %s", (list_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Lista não encontrada")
                cur.execute("DELETE FROM vehicle_lists WHERE id = %s", (list_id,))
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/")
def vehicles_query(list_id: int | None = None, plate: str | None = None):
    """Lista veículos com filtros opcionais."""
    try:
        query = """
            SELECT vli.id, vli.plate, vli.list_id, vl.name as list_name, vl.color as list_color, \
                   vli.notes, vli.created_at
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
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        items = []
        for r in rows:
            items.append({
                "id": r[0],
                "plate": r[1],
                "list_id": r[2],
                "list_name": r[3],
                "list_color": r[4],
                "notes": r[5],
                "created_at": r[6].isoformat() if r[6] else None
            })
        return {"items": items, "total": len(items)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/")
async def vehicles_create(request: Request):
    """Adiciona um veículo a uma lista."""
    try:
        data = await request.json()
        plate_raw = data.get("plate")
        if plate_raw is None or plate_raw == "":
            raise HTTPException(status_code=400, detail="plate é obrigatório")
        plate = str(plate_raw).strip().upper()
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
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM vehicle_lists WHERE id = %s", (list_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Lista não encontrada")
                try:
                    cur.execute("""
                        INSERT INTO vehicle_list_items (list_id, plate, notes)
                        VALUES (%s, %s, %s)
                        RETURNING id, created_at
                    """, (list_id, plate, notes))
                    r = cur.fetchone()
                except psycopg2.IntegrityError:
                    conn.rollback()
                    raise HTTPException(status_code=409, detail="Placa já existe nesta lista")
        return {
            "id": r[0],
            "plate": plate,
            "list_id": list_id,
            "notes": notes,
            "created_at": r[1].isoformat() if r[1] else None
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Erro: {str(e)}. Traceback: {tb}")

@router.delete("/{vid}")
def vehicles_delete(vid: int):
    """Remove um veículo de uma lista."""
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM vehicle_list_items WHERE id = %s", (vid,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Veículo não encontrado")
                cur.execute("DELETE FROM vehicle_list_items WHERE id = %s", (vid,))
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
