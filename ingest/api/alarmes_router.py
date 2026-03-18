from datetime import datetime, timezone
import logging
import uuid
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request


def build_alarmes_router(
    conn_factory: Callable[[], Any],
    require_role_fn: Callable[..., Any],
    assert_admin_fn: Callable[[Request, str], Any],
    assert_admin_or_operator_fn: Callable[[Request, str], Any],
    fcm_alert_cls: Any,
    send_alert_to_alarm_users_fn: Callable[..., Any],
    get_fcm_credential_identity_fn: Callable[[], dict[str, str]],
    logger_obj: logging.Logger,
) -> APIRouter:
    router = APIRouter(tags=["alarmes"])

    @router.get("/api/alarmes")
    async def list_alarmes(request: Request):
        """Listar todos os alarmes com listas e usuários vinculados."""
        require_role_fn(request, "admin", "operador", "visualizador")
        try:
            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT to_regclass('public.alarmes')")
                    has_alarmes_table = bool(cur.fetchone()[0])
                    if not has_alarmes_table:
                        logger_obj.warning("[ALARMES] Tabela public.alarmes não encontrada; retornando lista vazia")
                        return {"items": []}

                    cur.execute(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema='public' AND table_name='alarmes'
                        """
                    )
                    alarmes_cols = {row[0] for row in cur.fetchall()}

                    if "id" not in alarmes_cols:
                        logger_obj.error("[ALARMES] Coluna obrigatória 'id' ausente em public.alarmes")
                        return {"items": [], "detail": "Estrutura de alarmes inconsistente"}

                    if "nome" not in alarmes_cols:
                        logger_obj.error("[ALARMES] Coluna obrigatória 'nome' ausente em public.alarmes")
                        return {"items": [], "detail": "Estrutura de alarmes inconsistente"}

                    select_parts = [
                        "a.id AS id",
                        "a.nome AS nome",
                        ("a.descricao" if "descricao" in alarmes_cols else "''::text") + " AS descricao",
                        ("a.tipo" if "tipo" in alarmes_cols else "'placa_monitorada'::text") + " AS tipo",
                        ("a.prioridade" if "prioridade" in alarmes_cols else "'media'::text") + " AS prioridade",
                        ("a.ativo" if "ativo" in alarmes_cols else "TRUE") + " AS ativo",
                        ("a.mensagem" if "mensagem" in alarmes_cols else "''::text") + " AS mensagem",
                        ("a.criado_em" if "criado_em" in alarmes_cols else "NULL::timestamptz") + " AS criado_em",
                        ("a.atualizado_em" if "atualizado_em" in alarmes_cols else "NULL::timestamptz") + " AS atualizado_em",
                    ]
                    cur.execute(f"SELECT {', '.join(select_parts)} FROM alarmes a ORDER BY a.id DESC")

                    rows = cur.fetchall() or []
                    if not rows:
                        return {"items": []}

                    cur.execute("SELECT to_regclass('public.alarme_listas')")
                    has_alarme_listas = bool(cur.fetchone()[0])
                    cur.execute("SELECT to_regclass('public.alarme_usuarios')")
                    has_alarme_usuarios = bool(cur.fetchone()[0])

                    alarme_listas_ok = False
                    alarme_usuarios_ok = False

                    if has_alarme_listas:
                        cur.execute(
                            """
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_schema='public' AND table_name='alarme_listas'
                            """
                        )
                        cols = {row[0] for row in cur.fetchall()}
                        alarme_listas_ok = {"alarme_id", "lista_id"}.issubset(cols)
                        if not alarme_listas_ok:
                            logger_obj.warning("[ALARMES] Tabela alarme_listas sem colunas esperadas: %s", cols)

                    if has_alarme_usuarios:
                        cur.execute(
                            """
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_schema='public' AND table_name='alarme_usuarios'
                            """
                        )
                        cols = {row[0] for row in cur.fetchall()}
                        alarme_usuarios_ok = {"alarme_id", "usuario_id"}.issubset(cols)
                        if not alarme_usuarios_ok:
                            logger_obj.warning("[ALARMES] Tabela alarme_usuarios sem colunas esperadas: %s", cols)

                    alarmes = []
                    for row in rows:
                        aid, nome, descricao, tipo, prioridade, ativo, mensagem, criado_em, atualizado_em = row

                        if aid is None:
                            logger_obj.warning("[ALARMES] Registro ignorado por id nulo: %s", row)
                            continue

                        listas = []
                        usuarios = []

                        if alarme_listas_ok:
                            cur.execute("SELECT lista_id FROM alarme_listas WHERE alarme_id=%s", (aid,))
                            listas = [r[0] for r in (cur.fetchall() or []) if r and r[0] is not None]

                        if alarme_usuarios_ok:
                            cur.execute("SELECT usuario_id FROM alarme_usuarios WHERE alarme_id=%s", (aid,))
                            usuarios = [r[0] for r in (cur.fetchall() or []) if r and r[0] is not None]

                        alarmes.append(
                            {
                                "id": int(aid),
                                "nome": str(nome or ""),
                                "descricao": str(descricao or ""),
                                "tipo": str(tipo or "placa_monitorada"),
                                "prioridade": str(prioridade or "media"),
                                "ativo": bool(ativo),
                                "mensagem": str(mensagem or ""),
                                "criado_em": criado_em.isoformat() if isinstance(criado_em, datetime) else (str(criado_em) if criado_em else None),
                                "atualizado_em": atualizado_em.isoformat() if isinstance(atualizado_em, datetime) else (str(atualizado_em) if atualizado_em else None),
                                "listas": listas,
                                "usuarios": usuarios,
                            }
                        )

            return {"items": alarmes}
        except HTTPException:
            raise
        except Exception as exc:
            logger_obj.exception("[ALARMES] Erro em GET /api/alarmes: %s", exc)
            return {"items": [], "detail": "Erro ao listar alarmes"}

    @router.post("/api/alarmes", status_code=201)
    async def create_alarme(request: Request):
        assert_admin_or_operator_fn(request, "Apenas administradores e operadores podem criar alarmes")
        data = await request.json()
        lista_id = data.get("lista_id")
        if not lista_id:
            raise HTTPException(status_code=400, detail="lista_id é obrigatório")
        lista_id = int(lista_id)
        prioridade = str(data.get("prioridade") or "media").strip()
        if prioridade not in ("baixa", "media", "alta", "critica"):
            raise HTTPException(status_code=400, detail="prioridade inválida")
        ativo = bool(data.get("ativo", True))
        usuarios = data.get("usuarios") or []
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name FROM vehicle_lists WHERE id=%s", (lista_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=400, detail="Lista não encontrada")
                nome = f"Alarme - {row[0]}"
                cur.execute(
                    """
                    INSERT INTO alarmes (nome, descricao, tipo, prioridade, ativo, mensagem)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    RETURNING id
                    """,
                    (nome, "", "placa_monitorada", prioridade, ativo, ""),
                )
                aid = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO alarme_listas (alarme_id, lista_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (aid, lista_id),
                )
                for uid in usuarios:
                    cur.execute(
                        "INSERT INTO alarme_usuarios (alarme_id, usuario_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                        (aid, int(uid)),
                    )
        return {"id": aid, "ok": True}

    @router.put("/api/alarmes/{aid}")
    async def update_alarme(aid: int, request: Request):
        assert_admin_or_operator_fn(request, "Apenas administradores e operadores podem atualizar alarmes")
        data = await request.json()
        sets, vals = [], []
        lista_id = data.get("lista_id")
        if lista_id:
            lista_id = int(lista_id)
        if "prioridade" in data:
            prioridade = str(data["prioridade"]).strip()
            if prioridade not in ("baixa", "media", "alta", "critica"):
                raise HTTPException(status_code=400, detail="prioridade inválida")
            sets.append("prioridade=%s")
            vals.append(prioridade)
        if "ativo" in data:
            sets.append("ativo=%s")
            vals.append(bool(data["ativo"]))
        with conn_factory() as conn:
            with conn.cursor() as cur:
                if lista_id:
                    cur.execute("SELECT name FROM vehicle_lists WHERE id=%s", (lista_id,))
                    row = cur.fetchone()
                    if not row:
                        raise HTTPException(status_code=400, detail="Lista não encontrada")
                    sets.append("nome=%s")
                    vals.append(f"Alarme - {row[0]}")
                if sets:
                    sets.append("atualizado_em=NOW()")
                    vals.append(aid)
                    cur.execute(f"UPDATE alarmes SET {', '.join(sets)} WHERE id=%s", tuple(vals))
                    if cur.rowcount == 0:
                        raise HTTPException(status_code=404, detail="Alarme não encontrado")
                if lista_id:
                    cur.execute("DELETE FROM alarme_listas WHERE alarme_id=%s", (aid,))
                    cur.execute(
                        "INSERT INTO alarme_listas (alarme_id, lista_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                        (aid, lista_id),
                    )
                if "usuarios" in data:
                    cur.execute("DELETE FROM alarme_usuarios WHERE alarme_id=%s", (aid,))
                    for uid in (data["usuarios"] or []):
                        cur.execute(
                            "INSERT INTO alarme_usuarios (alarme_id, usuario_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                            (aid, int(uid)),
                        )
        return {"ok": True}

    @router.delete("/api/alarmes/{aid}", status_code=204)
    async def delete_alarme(aid: int, request: Request):
        assert_admin_or_operator_fn(request, "Apenas administradores e operadores podem deletar alarmes")
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM alarmes WHERE id=%s", (aid,))
                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Alarme não encontrado")

    @router.post("/api/alarmes/{aid}/test")
    async def test_alarme(aid: int, request: Request):
        """Dispara um alerta de teste para os usuários vinculados ao alarme."""
        assert_admin_or_operator_fn(request, "Apenas administradores e operadores podem testar alarmes")
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT nome, tipo, prioridade, mensagem FROM alarmes WHERE id=%s", (aid,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Alarme não encontrado")
                nome, tipo, prioridade, mensagem = row
                alert = fcm_alert_cls(
                    plate="TESTE-0000",
                    target_name=nome,
                    camera_name="Teste de alarme",
                    detected_at=datetime.now(timezone.utc).isoformat(),
                    image_url="",
                    event_id=f"alarm-test-{aid}-{uuid.uuid4().hex[:8]}",
                    city="N/A",
                    risk_level=prioridade,
                    alert_type=tipo,
                )
                stats = await send_alert_to_alarm_users_fn(
                    cur,
                    aid,
                    alert,
                    deactivate_invalid_tokens=False,
                    collect_results=True,
                )

        cred = get_fcm_credential_identity_fn()
        resultados = list(stats.get("resultados", []))
        token_ids = list(stats.get("token_ids", []))
        ok = any(bool(item.get("sucesso")) for item in resultados)

        return {
            "ok": ok,
            "alarm_id": aid,
            "alarm_name": nome,
            "tokens_encontrados": int(stats.get("tokens_encontrados", len(token_ids))),
            "tokens_testados": token_ids,
            "project_id": cred.get("project_id", ""),
            "client_email": cred.get("client_email", ""),
            "credentials_path": cred.get("credentials_path", ""),
            "resultados": resultados,
            "linked_users": int(stats.get("linked_users", 0)),
            "users_with_tokens": int(stats.get("users_with_tokens", 0)),
            "sent": int(stats.get("sent", 0)),
            "failed": int(stats.get("failed", 0)),
            "invalid_tokens": int(stats.get("invalid", 0)),
        }

    @router.get("/api/alarmes/historico")
    async def alarmes_historico(request: Request):
        """Retorna últimos 200 registros de alertas enviados (tabela alertas_criticos)."""
        assert_admin_fn(request, "Apenas administradores podem acessar histórico de alarmes")
        try:
            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT to_regclass('public.alertas_criticos')")
                    has_table = bool(cur.fetchone()[0])
                    if not has_table:
                        logger_obj.warning("[ALARMES] Tabela public.alertas_criticos não encontrada; retornando histórico vazio")
                        return {"items": []}

                    cur.execute(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema='public' AND table_name='alertas_criticos'
                        """
                    )
                    cols = {row[0] for row in cur.fetchall()}

                    if "id" not in cols:
                        logger_obj.error("[ALARMES] Coluna obrigatória 'id' ausente em public.alertas_criticos")
                        return {"items": [], "detail": "Estrutura de histórico inconsistente"}

                    select_parts = [
                        "id",
                        ("usuario_id" if "usuario_id" in cols else "NULL::integer") + " AS usuario_id",
                        ("evento_id" if "evento_id" in cols else "NULL::text") + " AS evento_id",
                        ("placa" if "placa" in cols else "''::text") + " AS placa",
                        ("camera_name" if "camera_name" in cols else "''::text") + " AS camera_name",
                        ("target_name" if "target_name" in cols else "''::text") + " AS target_name",
                        ("detected_at" if "detected_at" in cols else "NULL::timestamptz") + " AS detected_at",
                        ("risk_level" if "risk_level" in cols else "''::text") + " AS risk_level",
                        ("alert_type" if "alert_type" in cols else "''::text") + " AS alert_type",
                        ("criado_em" if "criado_em" in cols else "NULL::timestamptz") + " AS criado_em",
                        ("lido" if "lido" in cols else "FALSE") + " AS lido",
                        ("error_message" if "error_message" in cols else "''::text") + " AS error_message",
                    ]

                    order_col = "criado_em" if "criado_em" in cols else "id"
                    cur.execute(f"SELECT {', '.join(select_parts)} FROM alertas_criticos ORDER BY {order_col} DESC LIMIT 200")

                    rows = cur.fetchall() or []
                    if not rows:
                        return {"items": []}

                    items = []
                    for row in rows:
                        items.append(
                            {
                                "id": int(row[0]) if row[0] is not None else None,
                                "usuario_id": row[1],
                                "event_id": row[2],
                                "placa": str(row[3] or ""),
                                "camera_name": str(row[4] or ""),
                                "target_name": str(row[5] or ""),
                                "detected_at": row[6].isoformat() if isinstance(row[6], datetime) else (str(row[6]) if row[6] else None),
                                "risk_level": str(row[7] or ""),
                                "alert_type": str(row[8] or ""),
                                "criado_em": row[9].isoformat() if isinstance(row[9], datetime) else (str(row[9]) if row[9] else None),
                                "lido": bool(row[10]),
                                "error_message": str(row[11] or ""),
                            }
                        )

            return {"items": items}
        except HTTPException:
            raise
        except Exception as exc:
            logger_obj.exception("[ALARMES] Erro em GET /api/alarmes/historico: %s", exc)
            return {"items": [], "detail": "Erro ao carregar histórico de alarmes"}

    @router.post("/api/alarmes/historico/{alert_id}/read")
    async def alarmes_historico_mark_read(alert_id: int, request: Request):
        """Marca um alerta do histórico como lido."""
        require_role_fn(request, "admin", "operador", "visualizador")
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE alertas_criticos SET lido=TRUE WHERE id=%s", (alert_id,))
                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Alerta não encontrado")
        return {"ok": True, "id": alert_id, "lido": True}

    return router
