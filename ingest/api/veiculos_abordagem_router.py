from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request

from cadastro_support import _VEICULO_SELECT, _veiculo_row_to_dict


def build_veiculos_abordagem_router(
    conn_factory: Callable[[], Any],
    require_auth_fn: Callable[[Request], Any],
    assert_admin_or_operator_fn: Callable[[Request, str], Any],
    normalize_str_fn: Callable[[Optional[str]], Optional[str]],
) -> APIRouter:
    router = APIRouter(tags=["veiculos-abordagem"])

    @router.get("/api/veiculos-abordagem")
    def listar_veiculos_abordagem(
        request: Request,
        q: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ):
        """Lista veículos de abordagem. Busca por placa, marca ou modelo."""
        require_auth_fn(request)
        limit = max(1, min(200, int(limit)))
        offset = max(0, int(offset))
        with conn_factory() as conn:
            with conn.cursor() as cur:
                if q and q.strip():
                    term = f"%{q.strip().upper()}%"
                    where = " WHERE placa ILIKE %s OR marca ILIKE %s OR modelo ILIKE %s "
                    cur.execute(
                        _VEICULO_SELECT + where + "ORDER BY placa ASC LIMIT %s OFFSET %s",
                        (term, term, term, limit, offset),
                    )
                    rows = cur.fetchall()
                    cur.execute(
                        "SELECT COUNT(*) FROM veiculos_abordagem" + where,
                        (term, term, term),
                    )
                else:
                    cur.execute(_VEICULO_SELECT + "ORDER BY placa ASC LIMIT %s OFFSET %s", (limit, offset))
                    rows = cur.fetchall()
                    cur.execute("SELECT COUNT(*) FROM veiculos_abordagem")
                total = cur.fetchone()[0]
        return {"total": total, "veiculos": [_veiculo_row_to_dict(row) for row in rows]}

    @router.get("/api/veiculos-abordagem/busca")
    def buscar_veiculo_por_placa(request: Request, placa: str):
        """Busca um veículo pela placa exata (case-insensitive)."""
        require_auth_fn(request)
        placa_normalizada = (placa or "").strip().upper()
        if not placa_normalizada:
            raise HTTPException(status_code=400, detail="placa é obrigatória")
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(_VEICULO_SELECT + "WHERE placa = %s LIMIT 1", (placa_normalizada,))
                row = cur.fetchone()
        if not row:
            return {"found": False, "veiculo": None}
        return {"found": True, "veiculo": _veiculo_row_to_dict(row)}

    @router.get("/api/veiculos-abordagem/{veiculo_id}")
    def buscar_veiculo_abordagem_por_id(veiculo_id: int, request: Request):
        """Retorna um veículo de abordagem pelo id."""
        require_auth_fn(request)
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(_VEICULO_SELECT + "WHERE id=%s LIMIT 1", (veiculo_id,))
                row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Veículo não encontrado")
        return _veiculo_row_to_dict(row)

    @router.post("/api/veiculos-abordagem", status_code=201)
    async def criar_veiculo_abordagem(request: Request):
        """
        Cria ou retorna veículo de abordagem.
        Payload (JSON):
          placa*, marca, modelo, cor, ano (int), tipo, observacoes
        Se a placa já existir, retorna o existente sem duplicar (upsert por placa).
        """
        assert_admin_or_operator_fn(
            request,
            "Apenas administradores e operadores podem cadastrar veículos de abordagem",
        )
        data = await request.json()
        placa = (normalize_str_fn(data.get("placa")) or "").upper()
        if not placa:
            raise HTTPException(status_code=400, detail="placa é obrigatória")
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(_VEICULO_SELECT + "WHERE placa=%s LIMIT 1", (placa,))
                existing = cur.fetchone()
                if existing:
                    return {
                        "ok": True,
                        "id": existing[0],
                        "created": False,
                        "veiculo": _veiculo_row_to_dict(existing),
                    }
                ano_raw = data.get("ano")
                ano = int(ano_raw) if ano_raw and str(ano_raw).isdigit() else None
                cur.execute(
                    """
                    INSERT INTO veiculos_abordagem (placa, marca, modelo, cor, ano, tipo, observacoes)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id
                    """,
                    (
                        placa,
                        normalize_str_fn(data.get("marca")),
                        normalize_str_fn(data.get("modelo")),
                        normalize_str_fn(data.get("cor")),
                        ano,
                        normalize_str_fn(data.get("tipo")),
                        normalize_str_fn(data.get("observacoes")),
                    ),
                )
                new_id = cur.fetchone()[0]
        return {"ok": True, "id": new_id, "created": True}

    @router.put("/api/veiculos-abordagem/{veiculo_id}")
    async def atualizar_veiculo_abordagem(veiculo_id: int, request: Request):
        """Atualiza dados de um veículo de abordagem."""
        assert_admin_or_operator_fn(
            request,
            "Apenas administradores e operadores podem editar veículos de abordagem",
        )
        data = await request.json()
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(_VEICULO_SELECT + "WHERE id=%s LIMIT 1", (veiculo_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Veículo não encontrado")
                placa = (normalize_str_fn(data.get("placa")) or "").upper() or None
                ano_raw = data.get("ano")
                ano = int(ano_raw) if ano_raw and str(ano_raw).isdigit() else None
                cur.execute(
                    """
                    UPDATE veiculos_abordagem
                    SET placa=%s, marca=%s, modelo=%s, cor=%s, ano=%s, tipo=%s, observacoes=%s
                    WHERE id=%s
                    """,
                    (
                        placa,
                        normalize_str_fn(data.get("marca")),
                        normalize_str_fn(data.get("modelo")),
                        normalize_str_fn(data.get("cor")),
                        ano,
                        normalize_str_fn(data.get("tipo")),
                        normalize_str_fn(data.get("observacoes")),
                        veiculo_id,
                    ),
                )
        return {"ok": True}

    return router
