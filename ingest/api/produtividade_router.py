from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request

from auth_core import verify_password
from rbac import assert_admin, require_auth
from services.admin_activity_service import track_user_activity


def build_produtividade_router(conn_factory: Callable[[], Any]) -> APIRouter:
    router = APIRouter(tags=["produtividade"])

    def _safe_display_name(user: dict[str, Any]) -> str:
        return str(user.get("name") or user.get("sub") or "").strip()

    def _session_id(request: Request) -> str:
        return str(request.headers.get("X-BPFRON-Session") or "").strip()

    def _track_reset_activity(
        request: Request,
        user: dict[str, Any],
        activity_type: str,
        details: dict[str, Any],
    ) -> None:
        username = str(user.get("sub") or "").strip()
        if not username:
            return
        track_user_activity(
            conn_factory,
            request=request,
            username=username,
            full_name=_safe_display_name(user) or username,
            role=str(user.get("role") or "").strip(),
            session_id=_session_id(request),
            activity_type=activity_type,
            page_key="produtividade:reset",
            page_label="Produtividade / Zerar acumulado",
            page_path="/dashboard#produtividade/resumo",
            details=details,
        )

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
        # Os totais de abordados precisam refletir as ocorrencias registradas
        # no modulo de abordagens, e nao apenas cadastros unicos.
        cur.execute("SELECT COUNT(*) FROM abordagem_pessoas")
        pessoas_abordadas = int(cur.fetchone()[0] or 0)
        cur.execute("SELECT COUNT(*) FROM abordagens WHERE veiculo_id IS NOT NULL")
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
        modo = str(data.get("modo") or "substituir").strip().lower()
        modos_reset = {"zerar", "resetar", "limpar"}
        modos_incremento = {"incrementar", "somar", "adicionar", "acumular"}
        drogas_kg_input = data.get("drogas_apreendidas_kg", data.get("peso_kg", None))
        if drogas_kg_input in (None, "") and data.get("drogas_toneladas", None) not in (None, ""):
            drogas_kg_input = _coerce_float(data.get("drogas_toneladas", 0), "drogas_toneladas") * 1000.0
        payload = {
            "armas_apreendidas": _coerce_int(data.get("armas_apreendidas", 0), "armas_apreendidas"),
            "drogas_apreendidas_kg": _coerce_float(drogas_kg_input if drogas_kg_input not in (None, "") else 0, "drogas_apreendidas_kg"),
            "veiculos_recuperados": _coerce_int(data.get("veiculos_recuperados", 0), "veiculos_recuperados"),
            "updated_by": _safe_display_name(user),
        }
        is_reset_request = (
            modo in modos_reset
            or (
                modo not in modos_incremento
                and payload["armas_apreendidas"] == 0
                and payload["drogas_apreendidas_kg"] == 0
                and payload["veiculos_recuperados"] == 0
            )
        )

        if is_reset_request:
            senha_conf = str(data.get("senha_confirmacao") or data.get("current_password") or "").strip()
            if not senha_conf:
                _track_reset_activity(
                    request,
                    user,
                    "produtividade_reset_negado",
                    {
                        "result": "denied",
                        "reason": "missing_password",
                        "scope": "painel_produtividade",
                    },
                )
                raise HTTPException(status_code=422, detail="Digite sua senha para confirmar o reset.")

            username = str(user.get("sub") or "").strip()
            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT password_hash FROM users WHERE username=%s AND ativa=TRUE LIMIT 1",
                        (username,),
                    )
                    row = cur.fetchone()
            if not row or not verify_password(senha_conf, row[0]):
                _track_reset_activity(
                    request,
                    user,
                    "produtividade_reset_negado",
                    {
                        "result": "denied",
                        "reason": "invalid_password",
                        "scope": "painel_produtividade",
                    },
                )
                raise HTTPException(status_code=403, detail="Senha incorreta. Reset nao autorizado.")

        with conn_factory() as conn:
            with conn.cursor() as cur:
                _ensure_singleton(cur)
                if is_reset_request:
                    cur.execute(
                        """
                        UPDATE painel_produtividade
                        SET armas_apreendidas = 0,
                            drogas_apreendidas_kg = 0,
                            peso_kg = 0,
                            drogas_toneladas = 0,
                            veiculos_recuperados = 0,
                            updated_at = NOW(),
                            updated_by = %s
                        WHERE id = 1
                        """,
                        (payload["updated_by"],),
                    )
                    response_payload = _fetch_payload(cur)
                    _track_reset_activity(
                        request,
                        user,
                        "produtividade_reset",
                        {
                            "result": "success",
                            "scope": "painel_produtividade",
                            "fields_reset": [
                                "armas_apreendidas",
                                "drogas_apreendidas_kg",
                                "veiculos_recuperados",
                            ],
                        },
                    )
                    return response_payload
                elif modo in modos_incremento:
                    cur.execute(
                        """
                        UPDATE painel_produtividade
                        SET armas_apreendidas = COALESCE(armas_apreendidas, 0) + %s,
                            drogas_apreendidas_kg = COALESCE(drogas_apreendidas_kg, 0) + %s,
                            peso_kg = COALESCE(peso_kg, 0) + %s,
                            drogas_toneladas = COALESCE(drogas_toneladas, 0) + %s,
                            veiculos_recuperados = COALESCE(veiculos_recuperados, 0) + %s,
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
                else:
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
