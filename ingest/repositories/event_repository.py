# Camada de acesso ao banco de dados para eventos LPR
from typing import Any
from utils import _conn

class EventRepository:
    @staticmethod
    def list_events(page: int, limit: int, offset: int, plate: str | None, camera_id: str | None, dt_from: str | None, dt_to: str | None) -> tuple[list[dict], int]:
        where = []
        vals: list[Any] = []
        if plate:
            where.append("e.plate ILIKE %s")
            vals.append(f"%{plate.strip()}%")
        if camera_id:
            _cid = camera_id.strip()
            where.append("(e.camera_id = %s OR e.camera_ip = %s OR e.camera_id IN (SELECT camera_id FROM cameras WHERE ip = %s))")
            vals.extend([_cid, _cid, _cid])
        from utils import _parse_dt
        f = _parse_dt(dt_from)
        t = _parse_dt(dt_to)
        if f:
            where.append("COALESCE(e.occurred_at, e.ts) >= %s")
            vals.append(f)
        if t:
            where.append("COALESCE(e.occurred_at, e.ts) <= %s")
            vals.append(t)
        wsql = ("WHERE " + " AND ".join(where)) if where else ""
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM lpr_events e {wsql}", tuple(vals))
                total = int(cur.fetchone()[0])
                cur.execute(
                    f"""
                    SELECT e.id, e.plate, e.camera_id, e.channel_name, e.camera_ip, e.confidence,
                           e.image_path, COALESCE(e.occurred_at, e.ts) AS when_ts, e.yolo_result,
                           c.nome AS cam_nome, c.direcao
                    FROM lpr_events e
                    LEFT JOIN cameras c ON c.ip = e.camera_id OR c.ip = e.camera_ip
                    {wsql}
                    ORDER BY COALESCE(e.occurred_at, e.ts) DESC
                    LIMIT %s OFFSET %s
                    """,
                    tuple(vals + [limit, offset]),
                )
                rows = cur.fetchall()
        items = []
        import json as _json_lib
        for r in rows:
            ts = r[7].isoformat() if r[7] else None
            img = r[6]
            raw_yolo = r[8]
            if raw_yolo is None:
                yolo = None
            elif isinstance(raw_yolo, dict):
                yolo = raw_yolo
            else:
                yolo = _json_lib.loads(raw_yolo)
            items.append({
                "id": r[0],
                "plate": r[1],
                "camera_id": r[2],
                "channel_name": r[3],
                "camera_ip": r[4],
                "confidence": float(r[5] or 0.0),
                "image_path": img,
                "occurred_at": ts,
                "camera": r[9] or r[3],
                "timestamp": ts,
                "image": img,
                "thumb": img,
                "yolo_result": yolo,
                "sem_placa_motivo": yolo.get("sem_placa_motivo") if yolo else None,
                "vehicle_details":  yolo.get("vehicle_details")  if yolo else None,
                "image_quality":    yolo.get("image_quality")    if yolo else None,
                "cam_nome": r[9] or r[3],
                "direcao": r[10] or None,
            })
        return items, total
