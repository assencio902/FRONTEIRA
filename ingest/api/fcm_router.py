from datetime import datetime, timezone
import logging
import uuid
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request


def build_fcm_router(
    conn_factory: Callable[[], Any],
    assert_admin_fn: Callable[[Request, str], Any],
    resolve_user_id_fn: Callable[[str | None], str | None],
    register_fcm_token_fn: Callable[..., bool],
    is_likely_fake_token_fn: Callable[[str | None], bool],
    fcm_alert_cls: Any,
    send_alert_to_alarm_users_fn: Callable[..., Any],
    send_alert_to_user_tokens_fn: Callable[..., Any],
    get_fcm_credential_identity_fn: Callable[[], dict[str, str]],
    logger_obj: logging.Logger,
) -> APIRouter:
    router = APIRouter(tags=["fcm"])

    @router.post("/api/fcm/register-token")
    async def fcm_register_token(request: Request):
        """
        Registrar token FCM do dispositivo mobile.
        """
        try:
            user_sub = request.state.user.get("sub") if isinstance(request.state.user, dict) else None
            if not user_sub:
                raise HTTPException(status_code=401, detail="Não autenticado")

            user_id = resolve_user_id_fn(str(user_sub))
            if not user_id:
                raise HTTPException(status_code=422, detail="Usuário do token não mapeado no cadastro")

            data = await request.json()
            fcm_token = (data.get("fcm_token") or "").strip()
            device_id = (data.get("device_id") or "default").strip()

            if not fcm_token:
                raise HTTPException(status_code=422, detail="fcm_token obrigatório")

            if is_likely_fake_token_fn(fcm_token):
                logger_obj.warning(
                    "[FCM] register-token rejeitado (fake) user_sub=%s user_id=%s device_id=%s token_prefix=%s",
                    user_sub,
                    user_id,
                    device_id,
                    fcm_token[:16],
                )
                raise HTTPException(status_code=422, detail="fcm_token inválido para ambiente real")

            logger_obj.info(
                "[FCM] register-token request user_sub=%s user_id=%s device_id=%s token_len=%d",
                user_sub,
                user_id,
                device_id,
                len(fcm_token),
            )

            with conn_factory() as conn:
                with conn.cursor() as cur:
                    success = register_fcm_token_fn(user_id, device_id, fcm_token, db_cur=cur)
                    cur.execute(
                        "SELECT COUNT(*) FROM fcm_device_tokens WHERE user_id=%s AND active=TRUE",
                        (user_id,),
                    )
                    active_tokens = int(cur.fetchone()[0] or 0)

            if not success:
                raise HTTPException(status_code=500, detail="Erro ao registrar token")

            logger_obj.info(
                "[FCM] register-token success user_sub=%s user_id=%s device_id=%s active_tokens=%d token_prefix=%s",
                user_sub,
                user_id,
                device_id,
                active_tokens,
                fcm_token[:16],
            )

            return {
                "ok": True,
                "message": "Token FCM registrado com sucesso",
                "user_id": user_id,
                "user_sub": user_sub,
                "device_id": device_id,
                "active_tokens": active_tokens,
            }
        except HTTPException:
            raise
        except Exception as exc:
            logger_obj.error("[FCM] Erro ao registrar token: %s", exc)
            raise HTTPException(status_code=500, detail="Erro interno ao registrar token")

    @router.get("/api/fcm/my-token-status")
    async def fcm_my_token_status(request: Request):
        """Diagnóstico rápido dos tokens FCM do usuário autenticado."""
        try:
            user_sub = request.state.user.get("sub") if isinstance(request.state.user, dict) else None
            if not user_sub:
                raise HTTPException(status_code=401, detail="Não autenticado")

            user_id = resolve_user_id_fn(str(user_sub))
            if not user_id:
                raise HTTPException(status_code=422, detail="Usuário do token não mapeado no cadastro")

            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            COUNT(*) AS total,
                            COUNT(*) FILTER (WHERE active = TRUE) AS active,
                            COUNT(*) FILTER (WHERE active = FALSE) AS inactive,
                            MAX(updated_at) AS last_update,
                            MAX(last_seen_at) AS last_seen
                        FROM fcm_device_tokens
                        WHERE user_id = %s
                        """,
                        (user_id,),
                    )
                    row = cur.fetchone()

                    cur.execute(
                        """
                        SELECT device_id, active, updated_at, last_seen_at
                        FROM fcm_device_tokens
                        WHERE user_id = %s
                        ORDER BY updated_at DESC
                        """,
                        (user_id,),
                    )
                    devices = [
                        {
                            "device_id": d[0],
                            "active": bool(d[1]),
                            "updated_at": d[2].isoformat() if d[2] else None,
                            "last_seen_at": d[3].isoformat() if d[3] else None,
                        }
                        for d in cur.fetchall()
                    ]

            total = int(row[0] or 0)
            active = int(row[1] or 0)
            inactive = int(row[2] or 0)
            last_update = row[3].isoformat() if row[3] else None
            last_seen = row[4].isoformat() if row[4] else None

            logger_obj.info(
                "[FCM] my-token-status user_sub=%s user_id=%s total=%d active=%d inactive=%d",
                user_sub,
                user_id,
                total,
                active,
                inactive,
            )

            return {
                "ok": True,
                "user_sub": str(user_sub),
                "user_id": str(user_id),
                "total_tokens": total,
                "active_tokens": active,
                "inactive_tokens": inactive,
                "last_update": last_update,
                "last_seen": last_seen,
                "devices": devices,
            }
        except HTTPException:
            raise
        except Exception as exc:
            logger_obj.exception("[FCM] Erro em my-token-status: %s", exc)
            raise HTTPException(status_code=500, detail="Erro ao consultar status dos tokens FCM")

    @router.post("/api/fcm/send-alert")
    async def fcm_send_alert(request: Request):
        """Endpoint manual para teste de push para usuários vinculados a um alarme."""
        assert_admin_fn(request, "Apenas administradores podem enviar alerta manual")
        try:
            data = await request.json()
            alarme_id_raw = data.get("alarme_id")
            plate = str(data.get("plate") or "").strip().upper()
            target_name = str(data.get("target_name") or "Alvo monitorado").strip()
            camera_name = str(data.get("camera_name") or "Camera teste").strip()
            detected_at = str(data.get("detected_at") or datetime.now(timezone.utc).isoformat()).strip()
            image_url = str(data.get("image_url") or "").strip()
            event_id = str(data.get("event_id") or f"manual-{uuid.uuid4().hex[:12]}").strip()
            city = str(data.get("city") or "N/A").strip()
            risk_level = str(data.get("risk_level") or "high").strip().lower()
            alert_type = str(data.get("alert_type") or "critical_alert").strip().lower()

            if alarme_id_raw is None:
                raise HTTPException(status_code=422, detail="alarme_id é obrigatório")
            try:
                alarme_id = int(alarme_id_raw)
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail="alarme_id inválido")
            if not plate:
                raise HTTPException(status_code=422, detail="plate é obrigatório")

            alert = fcm_alert_cls(
                plate=plate,
                target_name=target_name,
                camera_name=camera_name,
                detected_at=detected_at,
                image_url=image_url,
                event_id=event_id,
                city=city,
                risk_level=risk_level,
                alert_type=alert_type,
            )

            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT ativo FROM alarmes WHERE id=%s LIMIT 1", (alarme_id,))
                    alarm_row = cur.fetchone()
                    if not alarm_row:
                        raise HTTPException(status_code=404, detail="Alarme não encontrado")
                    if not bool(alarm_row[0]):
                        raise HTTPException(status_code=422, detail="Alarme inativo")

                    cur.execute("SELECT COUNT(*) FROM alarme_usuarios WHERE alarme_id=%s", (alarme_id,))
                    linked_users = int(cur.fetchone()[0] or 0)
                    if linked_users == 0:
                        raise HTTPException(status_code=422, detail="Alarme sem usuários vinculados")

                    stats = await send_alert_to_alarm_users_fn(cur, alarme_id, alert)
                    if int(stats.get("users") or 0) == 0:
                        raise HTTPException(status_code=422, detail="Sem usuários elegíveis para envio")

            return {
                "ok": True,
                "linked_users": stats.get("linked_users", stats.get("users", 0)),
                "valid_tokens": stats.get("valid_tokens", 0),
                "sent": stats["sent"],
                "sent_success": stats["sent"],
                "failed": stats["failed"],
                "failures": stats["failed"],
                "invalid_tokens": stats["invalid"],
                "users": stats.get("users", 0),
                "users_with_tokens": stats.get("users_with_tokens", 0),
                "tokens_attempted": stats.get("tokens_attempted", stats.get("valid_tokens", 0)),
                "alarme_id": alarme_id,
                "event_id": event_id,
            }
        except HTTPException:
            raise
        except Exception as exc:
            logger_obj.exception("[FCM] Erro ao enviar alerta manual: %s", exc)
            raise HTTPException(status_code=500, detail="Erro interno ao enviar alerta push")

    @router.post("/api/fcm/test-self")
    async def fcm_test_self(request: Request):
        """Teste direto de push para o usuário autenticado."""
        try:
            user_sub = request.state.user.get("sub") if isinstance(request.state.user, dict) else None
            if not user_sub:
                raise HTTPException(status_code=401, detail="Não autenticado")

            user_id = resolve_user_id_fn(str(user_sub))
            if not user_id:
                raise HTTPException(status_code=422, detail="Usuário do token não mapeado no cadastro")

            data = await request.json()
            device_id = (data.get("device_id") or "").strip() or None
            title = str(data.get("title") or "Teste Push BPFRON").strip()
            body = str(data.get("body") or "Mensagem de teste enviada pelo backend").strip()
            event_id = str(data.get("event_id") or f"self-test-{uuid.uuid4().hex[:12]}").strip()

            logger_obj.info(
                "[FCM] test-self request user_sub=%s resolved_user_id=%s device_id=%s title=%s event_id=%s",
                user_sub,
                user_id,
                device_id or "*",
                title,
                event_id,
            )

            alert = fcm_alert_cls(
                plate="TESTE-SELF",
                target_name=title,
                camera_name="Teste Direto",
                detected_at=datetime.now(timezone.utc).isoformat(),
                image_url="",
                event_id=event_id,
                city="N/A",
                risk_level="high",
                alert_type="critical_alert",
            )

            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, user_id, device_id, LEFT(fcm_token, 16) AS token_prefix, active, updated_at
                        FROM fcm_device_tokens
                        WHERE user_id = %s
                        ORDER BY updated_at DESC
                        LIMIT 30
                        """,
                        (str(user_id),),
                    )
                    token_rows = cur.fetchall() or []

                    active_rows = [r for r in token_rows if bool(r[4])]
                    logger_obj.info(
                        "[FCM] test-self token_snapshot user_sub=%s user_id=%s total_rows=%d active_rows=%d",
                        user_sub,
                        user_id,
                        len(token_rows),
                        len(active_rows),
                    )
                    for row in token_rows:
                        logger_obj.info(
                            "[FCM] test-self token_row token_row_id=%s user_id=%s device_id=%s token_prefix=%s active=%s updated_at=%s",
                            row[0],
                            row[1],
                            row[2],
                            row[3],
                            row[4],
                            row[5],
                        )

                    stats = await send_alert_to_user_tokens_fn(cur, str(user_id), alert, device_id=device_id)

            if not isinstance(stats, dict):
                stats = {}

            def _safe_int(v):
                if v is None:
                    return 0
                try:
                    return int(v)
                except Exception:
                    return 0

            sent = _safe_int(stats.get("sent", 0))
            failed = _safe_int(stats.get("failed", 0))
            invalid = _safe_int(stats.get("invalid", 0))
            valid_tokens = _safe_int(stats.get("valid_tokens", 0))

            logger_obj.info(
                "[FCM] test-self user_sub=%s user_id=%s device_id=%s sent=%s failed=%s invalid=%s valid_tokens=%s",
                user_sub,
                user_id,
                device_id or "*",
                sent,
                failed,
                invalid,
                valid_tokens,
            )

            return {
                "ok": True,
                "user_sub": str(user_sub),
                "user_id": str(user_id),
                "device_id": device_id,
                "event_id": event_id,
                "valid_tokens": valid_tokens,
                "sent": sent,
                "failed": failed,
                "invalid_tokens": invalid,
                "payload": {
                    "title": title,
                    "body": body,
                    "type": "critical_alert",
                    "event_id": event_id,
                    "click_action": "FLUTTER_NOTIFICATION_CLICK",
                },
            }
        except HTTPException:
            raise
        except Exception as exc:
            logger_obj.exception("[FCM] Erro no test-self: %s", exc)
            raise HTTPException(status_code=500, detail="Erro interno no teste de push")

    @router.get("/api/fcm/status")
    async def fcm_status(request: Request):
        """Verificar status de alertas FCM."""
        assert_admin_fn(request, "Apenas administradores podem acessar status FCM")
        try:
            user_sub = request.state.user.get("sub") if isinstance(request.state.user, dict) else None
            if not user_sub:
                raise HTTPException(status_code=401, detail="Não autenticado")

            user_id = resolve_user_id_fn(str(user_sub))
            if not user_id:
                raise HTTPException(status_code=422, detail="Usuário do token não mapeado no cadastro")

            with conn_factory() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM alertas_criticos
                        WHERE usuario_id IN (%s, %s)
                        AND NOT lido
                        AND criado_em > NOW() - INTERVAL '24 hours'
                        """,
                        (user_id, str(user_sub)),
                    )
                    count = cur.fetchone()[0]

            return {
                "ok": True,
                "unread_alerts": count,
                "timestamp": datetime.now().isoformat(),
            }
        except HTTPException:
            raise
        except Exception as exc:
            logger_obj.error("[FCM] Erro ao verificar status: %s", exc)
            raise HTTPException(status_code=500, detail="Erro ao verificar status")

    return router
