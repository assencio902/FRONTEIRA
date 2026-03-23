from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request

from rbac import assert_admin_or_operator


def _clean_camera_required_fields(data: dict[str, Any]) -> dict[str, str]:
    return {
        "camera_id": str(data.get("camera_id") or "").strip(),
        "nome": str(data.get("nome") or "").strip(),
        "ip": str(data.get("ip") or "").strip(),
        "usuario": str(data.get("usuario") or "").strip(),
        "senha": str(data.get("senha") or "").strip(),
    }


def build_camera_router(
    conn_factory: Callable[[], Any],
    get_camera_row: Callable[[str], dict | None],
) -> APIRouter:
    router = APIRouter(tags=["cameras"])

    @router.get("/api/cameras")
    def list_cameras(include_inactive: bool = False):
        where = "" if include_inactive else "WHERE c.ativa = TRUE"
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT c.id, c.camera_id, c.nome, c.ativa, c.criticidade, c.peso,
                           c.created_at, c.ip,
                           s.last_seen, s.total_events, s.events_today,
                           c.direcao, c.latitude, c.longitude, c.modo_integracao, c.usuario,
                           le.last_event_camera_id, le.last_event_camera_ip, le.last_event_at
                    FROM cameras c
                    LEFT JOIN (
                        SELECT camera_id,
                               MAX(COALESCE(occurred_at, ts)) AS last_seen,
                               COUNT(*) AS total_events,
                               COUNT(*) FILTER (
                                   WHERE COALESCE(occurred_at, ts) >= CURRENT_DATE
                               ) AS events_today
                        FROM lpr_events
                        GROUP BY camera_id
                    ) s ON s.camera_id = c.camera_id
                          OR s.camera_id = c.ip
                    LEFT JOIN LATERAL (
                        SELECT
                            e.camera_id AS last_event_camera_id,
                            e.camera_ip AS last_event_camera_ip,
                            COALESCE(e.occurred_at, e.ts) AS last_event_at
                        FROM lpr_events e
                        WHERE e.camera_id = c.camera_id
                           OR e.camera_id = c.ip
                           OR (c.ip IS NOT NULL AND e.camera_ip = c.ip)
                        ORDER BY COALESCE(e.occurred_at, e.ts) DESC
                        LIMIT 1
                    ) le ON TRUE
                    {where}
                    ORDER BY c.id ASC
                    """
                )
                rows = cur.fetchall()

        items = []
        for row in rows:
            items.append(
                {
                    "id": row[0],
                    "camera_id": row[1],
                    "nome": row[2],
                    "ativa": row[3],
                    "criticidade": (row[4] or "NORMAL").upper(),
                    "peso_score": float(row[5] or 1.0),
                    "created_at": row[6].isoformat() if row[6] else None,
                    "ip": row[7],
                    "last_seen": row[8].isoformat() if row[8] else None,
                    "total_events": int(row[9] or 0),
                    "events_today": int(row[10] or 0),
                    "direcao": row[11] or None,
                    "latitude": float(row[12]) if row[12] is not None else None,
                    "longitude": float(row[13]) if row[13] is not None else None,
                    "modo_integracao": "push",
                    "usuario": row[15] or None,
                    "last_event_camera_id": row[16] or None,
                    "last_event_camera_ip": row[17] or None,
                    "last_event_at": row[18].isoformat() if row[18] else None,
                }
            )
        return {"items": items, "total": len(items)}

    @router.get("/api/cameras/status")
    def cameras_status():
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT camera_id, MAX(occurred_at) AS last_seen
                    FROM lpr_events
                    WHERE camera_id IS NOT NULL
                    GROUP BY camera_id
                    """
                )
                rows = cur.fetchall()
        result = {}
        for row in rows:
            result[row[0]] = row[1].isoformat() if row[1] else None
        return {"status": result}

    @router.post("/api/cameras")
    async def create_camera(request: Request):
        assert_admin_or_operator(
            request,
            "Apenas administradores e operadores podem criar cameras",
        )
        data = await request.json()
        required = _clean_camera_required_fields(data)
        camera_id = required["camera_id"]
        nome = required["nome"]
        ip = required["ip"]
        usuario = required["usuario"]
        senha = required["senha"]
        criticidade = (data.get("criticidade") or "NORMAL").strip().upper()
        peso = float(data.get("peso_score") or data.get("peso") or 1.0)
        direcao = (data.get("direcao") or "").strip().upper() or None
        latitude = float(data["latitude"]) if data.get("latitude") not in (None, "") else None
        longitude = float(data["longitude"]) if data.get("longitude") not in (None, "") else None

        if not camera_id or not nome or not ip or not usuario or not senha:
            raise HTTPException(
                status_code=400,
                detail="camera_id, nome, ip, usuario e senha sao obrigatorios",
            )
        if criticidade not in ("NORMAL", "CRITICA"):
            raise HTTPException(status_code=400, detail="criticidade deve ser 'NORMAL' ou 'CRITICA'")
        if peso <= 0:
            raise HTTPException(status_code=400, detail="peso deve ser > 0")
        if direcao and direcao not in ("CRESCENTE", "DECRESCENTE"):
            raise HTTPException(
                status_code=400,
                detail="direcao deve ser 'CRESCENTE' ou 'DECRESCENTE'",
            )

        with conn_factory() as conn:
            with conn.cursor() as cur:
                if ip:
                    cur.execute(
                        "SELECT camera_id FROM cameras WHERE ip=%s AND camera_id!=%s LIMIT 1",
                        (ip, camera_id),
                    )
                    dup = cur.fetchone()
                    if dup:
                        raise HTTPException(
                            status_code=400,
                            detail=f"IP {ip} ja esta em uso pela camera '{dup[0]}'",
                        )

                cur.execute(
                    """
                    INSERT INTO cameras (
                        camera_id, nome, ativa, criticidade, peso, peso_score,
                        ip, direcao, latitude, longitude, modo_integracao, usuario, senha
                    )
                    VALUES (%s, %s, TRUE, %s, %s, %s, %s, %s, %s, %s, 'push', %s, %s)
                    ON CONFLICT (camera_id) DO UPDATE SET
                        nome = EXCLUDED.nome,
                        ativa = TRUE,
                        criticidade = EXCLUDED.criticidade,
                        peso = EXCLUDED.peso,
                        peso_score = EXCLUDED.peso_score,
                        ip = EXCLUDED.ip,
                        direcao = EXCLUDED.direcao,
                        latitude = COALESCE(EXCLUDED.latitude, cameras.latitude),
                        longitude = COALESCE(EXCLUDED.longitude, cameras.longitude),
                        modo_integracao = 'push',
                        usuario = EXCLUDED.usuario,
                        senha = EXCLUDED.senha
                    """,
                    (
                        camera_id,
                        nome,
                        criticidade,
                        peso,
                        peso,
                        ip,
                        direcao,
                        latitude,
                        longitude,
                        usuario,
                        senha,
                    ),
                )

        return {"ok": True, "camera": get_camera_row(camera_id)}

    @router.put("/api/cameras/{cam_id}")
    async def update_camera(cam_id: int, request: Request):
        assert_admin_or_operator(
            request,
            "Apenas administradores e operadores podem editar cameras",
        )
        data = await request.json()
        nome = data.get("nome")
        criticidade = data.get("criticidade")
        peso = data.get("peso_score") or data.get("peso")
        ativa = data.get("ativa")
        new_cam_id = data.get("camera_id")
        ip = data.get("ip")
        usuario = data.get("usuario")
        senha = data.get("senha")
        direcao = data.get("direcao")

        if criticidade is not None:
            criticidade = str(criticidade).strip().upper()
            if criticidade not in ("NORMAL", "CRITICA"):
                raise HTTPException(
                    status_code=400,
                    detail="criticidade deve ser 'NORMAL' ou 'CRITICA'",
                )

        if peso is not None:
            peso = float(peso)
            if peso <= 0:
                raise HTTPException(status_code=400, detail="peso deve ser > 0")

        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT camera_id, nome, ip, usuario, senha
                    FROM cameras
                    WHERE id=%s
                    LIMIT 1
                    """,
                    (cam_id,),
                )
                existing = cur.fetchone()
                if not existing:
                    raise HTTPException(status_code=404, detail="camera nao encontrada")

                existing_camera_id = str(existing[0] or "").strip()
                existing_nome = str(existing[1] or "").strip()
                existing_ip = str(existing[2] or "").strip()
                existing_usuario = str(existing[3] or "").strip()
                existing_senha = str(existing[4] or "").strip()

                final_camera_id = (
                    str(new_cam_id).strip() if new_cam_id is not None else existing_camera_id
                )
                final_nome = str(nome).strip() if nome is not None else existing_nome
                final_ip = str(ip).strip() if ip is not None else existing_ip
                final_usuario = str(usuario).strip() if usuario is not None else existing_usuario
                final_senha = str(senha).strip() if senha is not None else existing_senha

                if not final_camera_id or not final_nome or not final_ip or not final_usuario or not final_senha:
                    raise HTTPException(
                        status_code=400,
                        detail="camera_id, nome, ip, usuario e senha sao obrigatorios",
                    )

                sets: list[str] = []
                vals: list[Any] = []

                if new_cam_id is not None:
                    sets.append("camera_id=%s")
                    vals.append(str(new_cam_id).strip())
                if nome is not None:
                    sets.append("nome=%s")
                    vals.append(str(nome).strip())
                if criticidade is not None:
                    sets.append("criticidade=%s")
                    vals.append(criticidade)
                if peso is not None:
                    sets.append("peso=%s")
                    vals.append(peso)
                    sets.append("peso_score=%s")
                    vals.append(peso)
                if ativa is not None:
                    sets.append("ativa=%s")
                    vals.append(bool(ativa))
                if ip is not None:
                    clean_ip = str(ip).strip()
                    cur.execute(
                        "SELECT camera_id FROM cameras WHERE ip=%s AND id!=%s LIMIT 1",
                        (clean_ip, cam_id),
                    )
                    dup = cur.fetchone()
                    if dup:
                        raise HTTPException(
                            status_code=400,
                            detail=f"IP {clean_ip} ja esta em uso pela camera '{dup[0]}'",
                        )
                    sets.append("ip=%s")
                    vals.append(clean_ip)
                if usuario is not None:
                    sets.append("usuario=%s")
                    vals.append(str(usuario).strip())
                if senha is not None:
                    sets.append("senha=%s")
                    vals.append(str(senha).strip())
                if direcao is not None:
                    d_val = str(direcao).strip().upper() or None
                    if d_val and d_val not in ("CRESCENTE", "DECRESCENTE"):
                        raise HTTPException(
                            status_code=400,
                            detail="direcao deve ser 'CRESCENTE' ou 'DECRESCENTE'",
                        )
                    sets.append("direcao=%s")
                    vals.append(d_val)
                if "latitude" in data:
                    lat_val = float(data["latitude"]) if data["latitude"] not in (None, "") else None
                    sets.append("latitude=%s")
                    vals.append(lat_val)
                if "longitude" in data:
                    lng_val = float(data["longitude"]) if data["longitude"] not in (None, "") else None
                    sets.append("longitude=%s")
                    vals.append(lng_val)

                sets.append("modo_integracao='push'")

                if sets:
                    vals.append(cam_id)
                    cur.execute(f"UPDATE cameras SET {', '.join(sets)} WHERE id=%s", tuple(vals))

        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, camera_id, nome, ativa, criticidade, peso, created_at, ip,
                           latitude, longitude, usuario
                    FROM cameras
                    WHERE id=%s
                    LIMIT 1
                    """,
                    (cam_id,),
                )
                row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="camera nao encontrada")

        peso_val = float(row[5] or 1.0)
        return {
            "id": row[0],
            "camera_id": row[1],
            "nome": row[2],
            "ativa": row[3],
            "criticidade": (row[4] or "NORMAL").upper(),
            "peso_score": peso_val,
            "peso": peso_val,
            "created_at": row[6].isoformat() if row[6] else None,
            "ip": row[7],
            "latitude": float(row[8]) if row[8] is not None else None,
            "longitude": float(row[9]) if row[9] is not None else None,
            "usuario": row[10] or None,
            "modo_integracao": "push",
        }

    @router.delete("/api/cameras/{cam_id}")
    def delete_camera(cam_id: int, request: Request):
        assert_admin_or_operator(
            request,
            "Apenas administradores e operadores podem deletar cameras",
        )
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM cameras WHERE id=%s", (cam_id,))
        return {"ok": True}

    return router
