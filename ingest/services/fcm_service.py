"""Serviço de notificações push via Firebase Cloud Messaging (FCM)."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

try:
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2 import service_account
except Exception:  # pragma: no cover - dependência opcional em dev
    GoogleAuthRequest = None
    service_account = None

logger = logging.getLogger(__name__)

FCM_API_URL = "https://fcm.googleapis.com/v1/projects/{}/messages:send"
FCM_CREDENTIALS_PATH = os.getenv("FCM_CREDENTIALS_PATH", "/app/secrets/firebase-adminsdk.json")
FCM_PROJECT_ID = os.getenv("FCM_PROJECT_ID", "")
FCM_SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]

_token_cache: dict[str, Any] = {"access_token": None, "expires_at": 0.0}


class FCMAlert:
    """Modelo de payload de alerta enviado ao app."""

    def __init__(
        self,
        plate: str,
        target_name: str,
        camera_name: str,
        detected_at: str,
        image_url: str,
        event_id: str,
        city: str = "N/A",
        risk_level: str = "normal",
        alert_type: str = "critical_alert",
    ):
        self.plate = plate
        self.target_name = target_name
        self.camera_name = camera_name
        self.detected_at = detected_at
        self.image_url = image_url
        self.event_id = event_id
        self.city = city
        self.risk_level = risk_level
        self.alert_type = alert_type

    def to_payload(self) -> dict[str, str]:
        return {
            "plate": self.plate,
            "target_name": self.target_name,
            "camera_name": self.camera_name,
            "detected_at": self.detected_at,
            "image_url": self.image_url,
            "event_id": self.event_id,
            "city": self.city,
            "risk_level": self.risk_level,
            "alert_type": self.alert_type,
            # compatibilidade com app legado
            "type": self.alert_type,
        }


def _resolve_project_id(credentials_info: dict[str, Any] | None = None) -> str:
    if FCM_PROJECT_ID:
        return FCM_PROJECT_ID
    if credentials_info and credentials_info.get("project_id"):
        return str(credentials_info["project_id"])
    raise RuntimeError("FCM_PROJECT_ID não configurado e project_id ausente no JSON de credenciais")


def _load_service_account_credentials():
    if service_account is None or GoogleAuthRequest is None:
        raise RuntimeError("google-auth não instalado no backend")
    if not os.path.exists(FCM_CREDENTIALS_PATH):
        raise RuntimeError(f"Credencial FCM não encontrada em {FCM_CREDENTIALS_PATH}")

    with open(FCM_CREDENTIALS_PATH, "r", encoding="utf-8") as fh:
        info = json.load(fh)

    creds = service_account.Credentials.from_service_account_file(
        FCM_CREDENTIALS_PATH,
        scopes=FCM_SCOPES,
    )
    return creds, info


def _get_access_token() -> tuple[str, str]:
    now = time.time()
    cached = _token_cache.get("access_token")
    if cached and float(_token_cache.get("expires_at") or 0.0) - 60 > now:
        project_id = _token_cache.get("project_id")
        if project_id:
            return cached, project_id

    creds, info = _load_service_account_credentials()
    creds.refresh(GoogleAuthRequest())
    access_token = creds.token
    if not access_token:
        raise RuntimeError("Não foi possível gerar access token para FCM")

    expiry = creds.expiry.timestamp() if creds.expiry else now + 3500
    project_id = _resolve_project_id(info)
    _token_cache.update({"access_token": access_token, "expires_at": expiry, "project_id": project_id})
    return access_token, project_id


def register_fcm_token(user_id: str, device_id: str, fcm_token: str, db_cur=None) -> bool:
    """Registra token FCM do dispositivo; persiste no banco quando cursor é fornecido."""
    if not db_cur:
        logger.warning("[FCM] register_fcm_token sem cursor de BD - token não será persistido")
        return False

    try:
        db_cur.execute(
            """
            INSERT INTO fcm_device_tokens (user_id, device_id, fcm_token, active, created_at, updated_at, last_seen_at)
            VALUES (%s, %s, %s, TRUE, NOW(), NOW(), NOW())
            ON CONFLICT (user_id, device_id)
            DO UPDATE SET
                fcm_token = EXCLUDED.fcm_token,
                active = TRUE,
                updated_at = NOW(),
                last_seen_at = NOW()
            """,
            (user_id, device_id, fcm_token),
        )
        logger.info("[FCM] Token registrado user=%s device=%s", user_id, device_id)
        return True
    except Exception as exc:
        logger.exception("[FCM] Falha ao registrar token: %s", exc)
        return False


async def _send_fcm_message(fcm_token: str, alert: FCMAlert) -> tuple[bool, str | None]:
    """Envia uma mensagem para um token FCM. Retorna (ok, erro)."""
    try:
        access_token, project_id = _get_access_token()
    except Exception as exc:
        logger.error("[FCM] Credencial/Token indisponível: %s", exc)
        return False, f"credentials_error:{exc}"

    channel_id = "critical_alerts" if alert.alert_type == "critical_alert" else "normal_alerts"
    title = "ALERTA CRITICO" if alert.alert_type == "critical_alert" else "Deteccao"
    body = f"{alert.target_name} - Placa {alert.plate}"

    payload = {
        "message": {
            "token": fcm_token,
            "notification": {
                "title": title,
                "body": body,
            },
            "data": alert.to_payload(),
            "android": {
                "priority": "HIGH",
                "notification": {
                    "channel_id": channel_id,
                    "click_action": "FLUTTER_NOTIFICATION_CLICK",
                    "sound": "alarm" if alert.alert_type == "critical_alert" else "default",
                },
            },
            "apns": {
                "headers": {"apns-priority": "10"},
                "payload": {
                    "aps": {
                        "sound": "default",
                        "badge": 1,
                    }
                },
            },
        }
    }

    url = FCM_API_URL.format(project_id)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, headers=headers, json=payload)

    if response.status_code == 200:
        logger.info("[FCM] Push enviado token=%s plate=%s", fcm_token[:18], alert.plate)
        return True, None

    response_text = response.text[:800]
    logger.error("[FCM] Falha HTTP %s: %s", response.status_code, response_text)

    is_unregistered = "UNREGISTERED" in response_text or "registration-token-not-registered" in response_text
    if is_unregistered:
        return False, "invalid_token"
    return False, f"http_{response.status_code}"


async def send_alert_to_user_tokens(
    db_cur,
    user_id: str,
    alert: FCMAlert,
    device_id: Optional[str] = None,
) -> dict[str, int]:
    """Envia alerta para tokens ativos do usuário e inativa tokens inválidos."""
    params = [user_id]
    sql = """
        SELECT id, fcm_token
        FROM fcm_device_tokens
        WHERE user_id = %s AND active = TRUE
    """
    if device_id:
        sql += " AND device_id = %s"
        params.append(device_id)

    db_cur.execute(sql, tuple(params))
    rows = db_cur.fetchall()
    if not rows:
        logger.warning("[FCM] Nenhum token ativo para user=%s", user_id)
        return {"sent": 0, "failed": 0, "invalid": 0}

    sent = 0
    failed = 0
    invalid = 0
    for token_row_id, token in rows:
        ok, error_code = await _send_fcm_message(token, alert)
        if ok:
            sent += 1
            db_cur.execute(
                "UPDATE fcm_device_tokens SET last_seen_at = NOW(), updated_at = NOW() WHERE id = %s",
                (token_row_id,),
            )
            continue

        failed += 1
        if error_code == "invalid_token":
            invalid += 1
            db_cur.execute(
                "UPDATE fcm_device_tokens SET active = FALSE, updated_at = NOW() WHERE id = %s",
                (token_row_id,),
            )

    return {"sent": sent, "failed": failed, "invalid": invalid}


async def send_alert_to_all_active_tokens(db_cur, alert: FCMAlert) -> dict[str, int]:
    """Envia alerta para todos os usuários com token ativo."""
    db_cur.execute("SELECT DISTINCT user_id FROM fcm_device_tokens WHERE active = TRUE")
    users = [row[0] for row in db_cur.fetchall()]

    totals = {"sent": 0, "failed": 0, "invalid": 0, "users": len(users)}
    for user_id in users:
        stats = await send_alert_to_user_tokens(db_cur, str(user_id), alert)
        totals["sent"] += stats["sent"]
        totals["failed"] += stats["failed"]
        totals["invalid"] += stats["invalid"]
    return totals


async def send_alert_for_detected_plate(
    db_cur,
    plate: str,
    camera_name: str,
    image_url: str,
    confidence: float,
    event_id: str,
    city: str = "N/A",
) -> bool:
    """Dispara push automaticamente quando placa monitorada é detectada."""
    plate_normalized = (plate or "").strip().upper()
    if not plate_normalized:
        return False

    try:
        # Prioridade 1: alvo rastreado explícito
        db_cur.execute(
            """
            SELECT a.id,
                   COALESCE(NULLIF(a.descricao, ''), a.plate) AS target_name,
                   COALESCE(vl.color, 'high') AS risk_level
            FROM alvos a
            LEFT JOIN vehicle_lists vl ON vl.id = a.list_id
            WHERE UPPER(a.plate) = %s
            LIMIT 1
            """,
            (plate_normalized,),
        )
        target_row = db_cur.fetchone()

        # Prioridade 2: placa em lista com alarme habilitado
        if not target_row:
            db_cur.execute(
                """
                SELECT NULL::INTEGER AS alvo_id,
                       COALESCE(vl.name, %s) AS target_name,
                       COALESCE(vl.color, 'high') AS risk_level
                FROM vehicle_list_items vli
                JOIN vehicle_lists vl ON vl.id = vli.list_id
                WHERE UPPER(vli.plate) = %s
                  AND COALESCE(vl.alarm_enabled, FALSE) = TRUE
                LIMIT 1
                """,
                (plate_normalized, plate_normalized),
            )
            target_row = db_cur.fetchone()

        if not target_row:
            logger.debug("[FCM] Placa %s não monitorada", plate_normalized)
            return False

        alvo_id, target_name, risk_level = target_row
        alert = FCMAlert(
            plate=plate_normalized,
            target_name=str(target_name or plate_normalized),
            camera_name=camera_name or "Camera desconhecida",
            detected_at=datetime.now(timezone.utc).isoformat(),
            image_url=image_url or "",
            event_id=str(event_id),
            city=city or "N/A",
            risk_level=(risk_level or "high"),
            alert_type="critical_alert",
        )

        stats = await send_alert_to_all_active_tokens(db_cur, alert)

        db_cur.execute(
            """
            INSERT INTO alertas_criticos (
                usuario_id, alvo_id, evento_id, placa, camera_name,
                target_name, detected_at, image_url, city, risk_level,
                alert_type, enviado_em, lido, error_message
            )
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, NOW(), FALSE, %s)
            """,
            (
                "broadcast",
                alvo_id,
                str(event_id),
                plate_normalized,
                alert.camera_name,
                alert.target_name,
                alert.image_url,
                alert.city,
                alert.risk_level,
                alert.alert_type,
                None if stats["sent"] > 0 else "no_active_tokens_or_send_failed",
            ),
        )

        logger.info(
            "[FCM] Auto-alerta plate=%s cam=%s conf=%.2f sent=%s failed=%s invalid=%s",
            plate_normalized,
            camera_name,
            confidence,
            stats["sent"],
            stats["failed"],
            stats["invalid"],
        )
        return stats["sent"] > 0
    except Exception as exc:
        logger.exception("[FCM] Erro no auto-alerta da placa %s: %s", plate_normalized, exc)
        return False
