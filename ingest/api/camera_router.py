from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request

from rbac import assert_admin_or_operator


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
                           c.direcao, c.latitude, c.longitude, c.modo_integracao, c.usuario
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
                    "modo_integracao": row[14] or "push",
                    "usuario": row[15] or None,
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
            "Apenas administradores e operadores podem criar câmeras",
        )
        data = await request.json()
        camera_id = (data.get("camera_id") or "").strip()
        nome = (data.get("nome") or "").strip()
        criticidade = (data.get("criticidade") or "NORMAL").strip().upper()
        peso = float(data.get("peso_score") or data.get("peso") or 1.0)
        ip = (data.get("ip") or "").strip() or None
        direcao = (data.get("direcao") or "").strip().upper() or None
        latitude = float(data["latitude"]) if data.get("latitude") not in (None, "") else None
        longitude = float(data["longitude"]) if data.get("longitude") not in (None, "") else None
        modo_integracao = (data.get("modo_integracao") or "push").strip().lower()
        usuario = (data.get("usuario") or "").strip() or None
        senha = (data.get("senha") or "").strip() or None

        if modo_integracao not in ("push", "listen"):
            raise HTTPException(status_code=400, detail="modo_integracao deve ser 'push' ou 'listen'")
        if modo_integracao == "listen" and (not usuario or not senha):
            raise HTTPException(
                status_code=400,
                detail="usuario e senha são obrigatórios no modo 'listen'",
            )
        if not camera_id or not nome:
            raise HTTPException(status_code=400, detail="camera_id e nome são obrigatórios")
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
                            detail=f"IP {ip} já está em uso pela câmera '{dup[0]}'",
                        )

                cur.execute(
                    """
                    INSERT INTO cameras (
                        camera_id, nome, ativa, criticidade, peso, peso_score,
                        ip, direcao, latitude, longitude, modo_integracao, usuario, senha
                    )
                    VALUES (%s, %s, TRUE, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (camera_id) DO UPDATE SET
                        nome = EXCLUDED.nome,
                        ativa = TRUE,
                        criticidade = EXCLUDED.criticidade,
                        peso = EXCLUDED.peso,
                        peso_score = EXCLUDED.peso_score,
                        ip = COALESCE(EXCLUDED.ip, cameras.ip),
                        direcao = EXCLUDED.direcao,
                        latitude = COALESCE(EXCLUDED.latitude, cameras.latitude),
                        longitude = COALESCE(EXCLUDED.longitude, cameras.longitude),
                        modo_integracao = EXCLUDED.modo_integracao,
                        usuario = COALESCE(EXCLUDED.usuario, cameras.usuario),
                        senha = COALESCE(EXCLUDED.senha, cameras.senha)
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
                        modo_integracao,
                        usuario,
                        senha,
                    ),
                )

        return {"ok": True, "camera": get_camera_row(camera_id)}

    @router.put("/api/cameras/{cam_id}")
    async def update_camera(cam_id: int, request: Request):
        assert_admin_or_operator(
            request,
            "Apenas administradores e operadores podem editar câmeras",
        )
        data = await request.json()
        nome = data.get("nome")
        criticidade = data.get("criticidade")
        peso = data.get("peso_score") or data.get("peso")
        ativa = data.get("ativa")
        new_cam_id = data.get("camera_id")
        ip = data.get("ip")
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
                cur.execute("SELECT 1 FROM cameras WHERE id=%s LIMIT 1", (cam_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="câmera não encontrada")

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
                    clean_ip = str(ip).strip() or None
                    if clean_ip:
                        cur.execute(
                            "SELECT camera_id FROM cameras WHERE ip=%s AND id!=%s LIMIT 1",
                            (clean_ip, cam_id),
                        )
                        dup = cur.fetchone()
                        if dup:
                            raise HTTPException(
                                status_code=400,
                                detail=f"IP {clean_ip} já está em uso pela câmera '{dup[0]}'",
                            )
                    sets.append("ip=%s")
                    vals.append(clean_ip)
                if direcao is not None:
                    d_val = str(direcao).strip().upper() or None
                    if d_val and d_val not in ("CRESCENTE", "DECRESCENTE"):
                        raise HTTPException(
                            status_code=400,
                            detail="direcao deve ser 'CRESCENTE' ou 'DECRESCENTE'",
                        )
                    sets.append("direcao=%s")
                    vals.append(d_val)
                if "modo_integracao" in data:
                    m_val = str(data["modo_integracao"]).strip().lower()
                    if m_val not in ("push", "listen"):
                        raise HTTPException(
                            status_code=400,
                            detail="modo_integracao deve ser 'push' ou 'listen'",
                        )
                    sets.append("modo_integracao=%s")
                    vals.append(m_val)
                if "usuario" in data:
                    sets.append("usuario=%s")
                    vals.append(str(data["usuario"]).strip() or None)
                if "senha" in data:
                    sets.append("senha=%s")
                    vals.append(str(data["senha"]).strip() or None)
                if "latitude" in data:
                    lat_val = float(data["latitude"]) if data["latitude"] not in (None, "") else None
                    sets.append("latitude=%s")
                    vals.append(lat_val)
                if "longitude" in data:
                    lng_val = float(data["longitude"]) if data["longitude"] not in (None, "") else None
                    sets.append("longitude=%s")
                    vals.append(lng_val)

                if sets:
                    vals.append(cam_id)
                    cur.execute(f"UPDATE cameras SET {', '.join(sets)} WHERE id=%s", tuple(vals))

        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, camera_id, nome, ativa, criticidade, peso, created_at, ip,
                           latitude, longitude, usuario, modo_integracao
                    FROM cameras
                    WHERE id=%s
                    LIMIT 1
                    """,
                    (cam_id,),
                )
                row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="câmera não encontrada")

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
            "modo_integracao": row[11] or "push",
        }

    @router.delete("/api/cameras/{cam_id}")
    def delete_camera(cam_id: int, request: Request):
        assert_admin_or_operator(
            request,
            "Apenas administradores e operadores podem deletar câmeras",
        )
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM cameras WHERE id=%s", (cam_id,))
        return {"ok": True}

    return router
