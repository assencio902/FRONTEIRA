from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request

from rbac import assert_admin, require_auth


def build_produtividade_router(conn_factory: Callable[[], Any]) -> APIRouter:
    router = APIRouter(tags=["produtividade"])

    def _safe_display_name(user: dict[str, Any]) -> str:
        return str(user.get("name") or user.get("sub") or "").strip()

    def _coerce_int(value: Any, field_name: str) -> int:
        try:
            number = int(float(str(value).replace(",", ".")))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"{field_name} invalido") from exc
        if number < 0:
            raise HTTPException(status_code=400, detail=f"{field_name} nao pode ser negativo")
        return number

    def _coerce_float(value: Any, field_name: str) -> float:
        try:
            number = float(str(value).replace(",", "."))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"{field_name} invalido") from exc
        if number < 0:
            raise HTTPException(status_code=400, detail=f"{field_name} nao pode ser negativo")
        return number

    def _ensure_singleton(cur: Any) -> None:
        cur.execute("INSERT INTO painel_produtividade (id) VALUES (1) ON CONFLICT (id) DO NOTHING")

    def _fetch_payload(cur: Any) -> dict[str, Any]:
        _ensure_singleton(cur)
        cur.execute(
            """
            SELECT id, armas_apreendidas, drogas_apreendidas_kg, peso_kg, drogas_toneladas, veiculos_recuperados, updated_at, updated_by
            FROM painel_produtividade
            WHERE id = 1
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=500, detail="produtividade indisponivel")
        drogas_apreendidas_kg = float(row[2] or 0)
        if drogas_apreendidas_kg <= 0 and float(row[3] or 0) > 0:
            drogas_apreendidas_kg = float(row[3] or 0)
        if drogas_apreendidas_kg <= 0 and float(row[4] or 0) > 0:
            drogas_apreendidas_kg = float(row[4] or 0) * 1000.0
        cur.execute("SELECT COUNT(DISTINCT pessoa_id) FROM abordagem_pessoas")
        pessoas_abordadas = int(cur.fetchone()[0] or 0)
        cur.execute("SELECT COUNT(*) FROM veiculos_abordagem")
        veiculos_abordados = int(cur.fetchone()[0] or 0)
        return {
            "id": int(row[0]),
            "armas_apreendidas": int(row[1] or 0),
            "drogas_apreendidas_kg": drogas_apreendidas_kg,
            "drogas_apreendidas_toneladas": drogas_apreendidas_kg / 1000.0,
            "veiculos_recuperados": int(row[5] or 0),
            "pessoas_abordadas": pessoas_abordadas,
            "veiculos_abordados": veiculos_abordados,
            "updated_at": row[6].isoformat() if row[6] else None,
            "updated_by": row[7] or "",
            # Compatibilidade com a versao anterior do card
            "peso_kg": drogas_apreendidas_kg,
            "drogas_toneladas": drogas_apreendidas_kg / 1000.0,
        }

    async def _safe_json(request: Request) -> dict[str, Any]:
        try:
            data = await request.json()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @router.get("/api/produtividade")
    async def get_produtividade(request: Request):
        require_auth(request)
        with conn_factory() as conn:
            with conn.cursor() as cur:
                return _fetch_payload(cur)

    @router.put("/api/produtividade")
    async def update_produtividade(request: Request):
        assert_admin(request, "Apenas administradores podem atualizar a produtividade")
        data = await _safe_json(request)
        user = require_auth(request)
        drogas_kg_input = data.get("drogas_apreendidas_kg", data.get("peso_kg", None))
        if drogas_kg_input in (None, "") and data.get("drogas_toneladas", None) not in (None, ""):
            drogas_kg_input = _coerce_float(data.get("drogas_toneladas", 0), "drogas_toneladas") * 1000.0
        payload = {
            "armas_apreendidas": _coerce_int(data.get("armas_apreendidas", 0), "armas_apreendidas"),
            "drogas_apreendidas_kg": _coerce_float(drogas_kg_input if drogas_kg_input not in (None, "") else 0, "drogas_apreendidas_kg"),
            "veiculos_recuperados": _coerce_int(data.get("veiculos_recuperados", 0), "veiculos_recuperados"),
            "updated_by": _safe_display_name(user),
        }

        with conn_factory() as conn:
            with conn.cursor() as cur:
                _ensure_singleton(cur)
                cur.execute(
                    """
                    UPDATE painel_produtividade
                    SET armas_apreendidas = %s,
                        drogas_apreendidas_kg = %s,
                        peso_kg = %s,
                        drogas_toneladas = %s,
                        veiculos_recuperados = %s,
                        updated_at = NOW(),
                        updated_by = %s
                    WHERE id = 1
                    """,
                    (
                        payload["armas_apreendidas"],
                        payload["drogas_apreendidas_kg"],
                        payload["drogas_apreendidas_kg"],
                        payload["drogas_apreendidas_kg"] / 1000.0,
                        payload["veiculos_recuperados"],
                        payload["updated_by"],
                    ),
                )
                return _fetch_payload(cur)

    return router
