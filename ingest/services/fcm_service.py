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
_credential_info_cache: dict[str, Any] = {}

SELECT_ACTIVE_USER_TOKENS_SQL = """
    SELECT id, user_id, device_id, fcm_token
    FROM fcm_device_tokens
    WHERE user_id = %s AND active = TRUE
"""


def normalize_plate(value: str | None) -> str:
    """Normaliza placa para comparação consistente (A-Z0-9, sem separadores)."""
    raw = (value or "").strip().upper()
    return "".join(ch for ch in raw if ch.isalnum())


def is_likely_fake_token(token: str | None) -> bool:
    """Detecta tokens de teste/mock para evitar uso em ambiente real."""
    val = (token or "").strip()
    if not val:
        return True
    lower = val.lower()
    suspicious_markers = (
        "dummy",
        "e2e",
        "test-token",
        "fake",
        "mock",
        "sample-token",
    )
    return any(marker in lower for marker in suspicious_markers)


def _token_prefix(token: str | None) -> str:
    val = (token or "").strip()
    return val[:16] if val else ""


def _compact_sql(sql: str) -> str:
    return " ".join((sql or "").split())


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
            "occurred_at": self.detected_at,
            "image_url": self.image_url,
            "event_id": self.event_id,
            "city": self.city,
            "risk_level": self.risk_level,
            "alert_type": self.alert_type,
            # compatibilidade com app legado
            "type": self.alert_type,
            "click_action": "FLUTTER_NOTIFICATION_CLICK",
            "screen": "alert_detail",
            "route": "/alert-detail",
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

    project_id = _resolve_project_id(info)
    client_email = str(info.get("client_email") or "")
    _credential_info_cache.update(
        {
            "credentials_path": FCM_CREDENTIALS_PATH,
            "project_id": project_id,
            "client_email": client_email,
        }
    )
    logger.info(
        "[FCM] credencial carregada path=%s project_id=%s client_email=%s",
        FCM_CREDENTIALS_PATH,
        project_id,
        client_email,
    )

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


def get_fcm_credential_identity() -> dict[str, str]:
    """Retorna metadados da credencial FCM atualmente configurada."""
    if _credential_info_cache:
        return {
            "credentials_path": str(_credential_info_cache.get("credentials_path") or FCM_CREDENTIALS_PATH),
            "project_id": str(_credential_info_cache.get("project_id") or ""),
            "client_email": str(_credential_info_cache.get("client_email") or ""),
        }

    if not os.path.exists(FCM_CREDENTIALS_PATH):
        return {
            "credentials_path": FCM_CREDENTIALS_PATH,
            "project_id": "",
            "client_email": "",
        }

    with open(FCM_CREDENTIALS_PATH, "r", encoding="utf-8") as fh:
        info = json.load(fh)

    project_id = _resolve_project_id(info)
    client_email = str(info.get("client_email") or "")
    _credential_info_cache.update(
        {
            "credentials_path": FCM_CREDENTIALS_PATH,
            "project_id": project_id,
            "client_email": client_email,
        }
    )
    return {
        "credentials_path": FCM_CREDENTIALS_PATH,
        "project_id": project_id,
        "client_email": client_email,
    }


def register_fcm_token(user_id: str, device_id: str, fcm_token: str, db_cur=None) -> bool:
    """Registra token FCM do dispositivo; persiste no banco quando cursor é fornecido."""
    if not db_cur:
        logger.warning("[FCM] register_fcm_token sem cursor de BD - token não será persistido")
        return False

    try:
        if is_likely_fake_token(fcm_token):
            logger.warning(
                "[FCM] Token rejeitado por padrão fake user=%s device=%s token_prefix=%s",
                user_id,
                device_id,
                (fcm_token or "")[:16],
            )
            return False

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


def _classify_fcm_failure(response: httpx.Response) -> tuple[str, str, bool]:
    response_text = response.text[:800]
    detail = response_text
    markers: list[str] = []

    try:
        payload = response.json()
    except Exception:
        payload = None

    if isinstance(payload, dict):
        error_obj = payload.get("error") if isinstance(payload.get("error"), dict) else payload
        for key in ("status", "message"):
            value = error_obj.get(key) if isinstance(error_obj, dict) else None
            if value:
                markers.append(str(value))

        details = error_obj.get("details") if isinstance(error_obj, dict) else None
        if isinstance(details, list):
            for item in details:
                if not isinstance(item, dict):
                    continue
                error_code = item.get("errorCode")
                if error_code:
                    markers.append(str(error_code))
                field_violations = item.get("fieldViolations")
                if isinstance(field_violations, list):
                    for violation in field_violations:
                        if not isinstance(violation, dict):
                            continue
                        description = violation.get("description")
                        if description:
                            markers.append(str(description))

        if markers:
            detail = " | ".join(markers)

    haystack = f"{response_text} {' '.join(markers)}".lower()
    invalid_markers = (
        "unregistered",
        "registration-token-not-registered",
        "not registered",
        "requested entity was not found",
        "requested entity was not found.",
    )
    is_invalid = any(marker in haystack for marker in invalid_markers)
    project_markers = (
        "project was not found",
        "project not found",
        "sender id",
        "mismatched-credential",
    )
    is_project_mismatch = any(marker in haystack for marker in project_markers)

    if is_invalid:
        error_code = "invalid_token"
    elif is_project_mismatch:
        error_code = "project_mismatch"
    else:
        error_code = f"http_{response.status_code}"
    return error_code, detail, is_invalid


def _extract_firebase_error_fields(response: httpx.Response) -> dict[str, str]:
    firebase_status = ""
    firebase_error = ""
    firebase_message = ""
    try:
        payload = response.json()
    except Exception:
        payload = None

    if isinstance(payload, dict):
        error_obj = payload.get("error") if isinstance(payload.get("error"), dict) else payload
        if isinstance(error_obj, dict):
            firebase_status = str(error_obj.get("status") or "")
            firebase_message = str(error_obj.get("message") or "")
            details = error_obj.get("details")
            if isinstance(details, list):
                for item in details:
                    if not isinstance(item, dict):
                        continue
                    code = item.get("errorCode")
                    if code:
                        firebase_error = str(code)
                        break

    return {
        "firebase_status": firebase_status,
        "firebase_error": firebase_error,
        "firebase_message": firebase_message,
    }


def _deactivate_token(db_cur, token_row_id: int, reason: str) -> None:
    db_cur.execute(
        "UPDATE fcm_device_tokens SET active = FALSE, updated_at = NOW() WHERE id = %s",
        (token_row_id,),
    )
    logger.warning("[FCM] token desativado token_row_id=%s reason=%s", token_row_id, reason)


async def _send_fcm_message(fcm_token: str, alert: FCMAlert) -> dict[str, Any]:
    """Envia uma mensagem para um token FCM. Retorna detalhes do resultado."""
    try:
        access_token, project_id = _get_access_token()
    except Exception as exc:
        logger.error("[FCM] Credencial/Token indisponível: %s", exc)
        return {
            "ok": False,
            "error_code": "credentials_error",
            "error_detail": str(exc),
            "invalid_token": False,
            "http_status": None,
        }

    channel_id = "critical_alerts" if alert.alert_type == "critical_alert" else "normal_alerts"
    title = "ALERTA CRITICO" if alert.alert_type == "critical_alert" else "Deteccao"
    body = f"{alert.target_name} - Placa {alert.plate}"

    notification_payload = {
        "title": title,
        "body": body,
    }
    if alert.image_url:
        notification_payload["image"] = alert.image_url

    android_notification_payload = {
        "channel_id": channel_id,
        "click_action": "FLUTTER_NOTIFICATION_CLICK",
        "sound": "default",
    }
    if alert.image_url:
        android_notification_payload["image"] = alert.image_url

    payload = {
        "message": {
            "token": fcm_token,
            "notification": notification_payload,
            "data": alert.to_payload(),
            "android": {
                "priority": "HIGH",
                "notification": android_notification_payload,
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

    payload_log = {
        "message": {
            **payload["message"],
            "token": f"{_token_prefix(fcm_token)}...",
        }
    }

    logger.info(
        "[FCM] payload event_id=%s plate=%s image_url=%s route=%s has_notification=%s has_data=%s project_id=%s body=%s",
        alert.event_id,
        alert.plate,
        "yes" if alert.image_url else "no",
        "/alert-detail",
        bool(payload.get("message", {}).get("notification")),
        bool(payload.get("message", {}).get("data")),
        project_id,
        json.dumps(payload_log, ensure_ascii=False),
    )

    url = FCM_API_URL.format(project_id)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, headers=headers, json=payload)
    except Exception as exc:
        logger.exception("[FCM] Exceção ao chamar Firebase token=%s", _token_prefix(fcm_token))
        return {
            "ok": False,
            "error_code": "firebase_request_exception",
            "error_detail": str(exc),
            "invalid_token": False,
            "http_status": None,
            "firebase_status": "",
            "firebase_error": "",
            "firebase_message": str(exc),
            "firebase_message_id": None,
        }

    if response.status_code == 200:
        firebase_message_id = None
        try:
            resp_payload = response.json()
            firebase_message_id = resp_payload.get("name") if isinstance(resp_payload, dict) else None
        except Exception:
            firebase_message_id = None

        logger.info(
            "[FCM] Push enviado token=%s plate=%s firebase_response=%s",
            fcm_token[:18],
            alert.plate,
            response.text,
        )
        return {
            "ok": True,
            "error_code": None,
            "error_detail": None,
            "invalid_token": False,
            "http_status": response.status_code,
            "firebase_status": "OK",
            "firebase_error": "",
            "firebase_message": "",
            "firebase_message_id": firebase_message_id,
        }

    error_code, error_detail, invalid_token = _classify_fcm_failure(response)
    firebase_fields = _extract_firebase_error_fields(response)
    logger.error(
        "[FCM] Falha HTTP %s token=%s detail=%s firebase_response=%s",
        response.status_code,
        _token_prefix(fcm_token),
        error_detail,
        response.text,
    )
    return {
        "ok": False,
        "error_code": error_code,
        "error_detail": error_detail,
        "invalid_token": invalid_token,
        "http_status": response.status_code,
        "firebase_status": firebase_fields["firebase_status"],
        "firebase_error": firebase_fields["firebase_error"],
        "firebase_message": firebase_fields["firebase_message"],
        "firebase_message_id": None,
    }


async def send_alert_to_user_tokens(
    db_cur,
    user_id: str,
    alert: FCMAlert,
    device_id: Optional[str] = None,
    *,
    deactivate_invalid_tokens: bool = True,
    collect_results: bool = False,
) -> dict[str, Any]:
    """Envia alerta para tokens ativos do usuário e inativa tokens inválidos."""
    params = [user_id]
    sql = SELECT_ACTIVE_USER_TOKENS_SQL
    if device_id:
        sql += " AND device_id = %s"
        params.append(device_id)
    sql += " ORDER BY id"

    logger.info("[FCM] SQL busca tokens: %s | params=%s", _compact_sql(sql), tuple(params))

    db_cur.execute(sql, tuple(params))
    rows = db_cur.fetchall()
    if not rows:
        logger.warning("[FCM] Nenhum token ativo para user_id=%s device_id=%s", user_id, device_id or "*")
        return {
            "sent": 0,
            "failed": 0,
            "invalid": 0,
            "valid_tokens": 0,
            "tokens_encontrados": 0,
            "token_ids": [],
            "resultados": [],
        }

    logger.info("[FCM] user_id=%s tokens_ativos_encontrados=%d device_id=%s", user_id, len(rows), device_id or "*")

    sent = 0
    failed = 0
    invalid = 0
    valid_tokens = 0
    token_ids = [int(r[0]) for r in rows]
    resultados: list[dict[str, Any]] = []
    for token_row_id, token_user_id, token_device_id, token in rows:
        token_prefix = _token_prefix(token)
        if is_likely_fake_token(token):
            logger.warning(
                "[FCM] envio_push user_id=%s device_id=%s token_row_id=%s token_prefix=%s resultado=fake_token",
                token_user_id,
                token_device_id,
                token_row_id,
                token_prefix,
            )
            failed += 1
            invalid += 1
            if deactivate_invalid_tokens:
                _deactivate_token(db_cur, token_row_id, "fake_token")
            if collect_results:
                resultados.append(
                    {
                        "token_id": int(token_row_id),
                        "user_id": str(token_user_id),
                        "device_id": str(token_device_id),
                        "token_prefix": token_prefix,
                        "sucesso": False,
                        "erro": "FAKE_TOKEN",
                        "detalhe": "Token marcado como teste/mock",
                    }
                )
            continue

        valid_tokens += 1
        logger.info(
            "[FCM] envio_push user_id=%s device_id=%s token_row_id=%s token_prefix=%s resultado=attempt",
            token_user_id,
            token_device_id,
            token_row_id,
            token_prefix,
        )

        result = await _send_fcm_message(token, alert)
        if result["ok"]:
            sent += 1
            db_cur.execute(
                "UPDATE fcm_device_tokens SET last_seen_at = NOW(), updated_at = NOW() WHERE id = %s",
                (token_row_id,),
            )
            logger.info(
                "[FCM] envio_push user_id=%s device_id=%s token_row_id=%s token_prefix=%s resultado=success http_status=%s",
                token_user_id,
                token_device_id,
                token_row_id,
                token_prefix,
                result["http_status"],
            )
            if collect_results:
                resultados.append(
                    {
                        "token_id": int(token_row_id),
                        "user_id": str(token_user_id),
                        "device_id": str(token_device_id),
                        "token_prefix": token_prefix,
                        "sucesso": True,
                        "firebase_message_id": result.get("firebase_message_id"),
                    }
                )
            continue

        failed += 1
        if result["invalid_token"]:
            invalid += 1
            if deactivate_invalid_tokens:
                _deactivate_token(db_cur, token_row_id, result["error_code"] or "invalid_token")

        logger.warning(
            "[FCM] envio_push user_id=%s device_id=%s token_row_id=%s token_prefix=%s resultado=failed error_code=%s detail=%s",
            token_user_id,
            token_device_id,
            token_row_id,
            token_prefix,
            result["error_code"],
            result["error_detail"],
        )
        if collect_results:
            resultados.append(
                {
                    "token_id": int(token_row_id),
                    "user_id": str(token_user_id),
                    "device_id": str(token_device_id),
                    "token_prefix": token_prefix,
                    "sucesso": False,
                    "erro": result.get("firebase_error") or result.get("firebase_status") or result.get("error_code"),
                    "detalhe": result.get("firebase_message") or result.get("error_detail"),
                }
            )

    return {
        "sent": sent,
        "failed": failed,
        "invalid": invalid,
        "valid_tokens": valid_tokens,
        "tokens_encontrados": len(rows),
        "token_ids": token_ids,
        "resultados": resultados,
    }


async def send_alert_to_all_active_tokens(db_cur, alert: FCMAlert) -> dict[str, int]:
    """Envia alerta para todos os usuários com token ativo."""
    db_cur.execute("SELECT DISTINCT user_id FROM fcm_device_tokens WHERE active = TRUE")
    users = [row[0] for row in db_cur.fetchall()]

    totals = {"sent": 0, "failed": 0, "invalid": 0, "users": len(users), "valid_tokens": 0}
    for user_id in users:
        stats = await send_alert_to_user_tokens(db_cur, str(user_id), alert)
        totals["sent"] += stats["sent"]
        totals["failed"] += stats["failed"]
        totals["invalid"] += stats["invalid"]
        totals["valid_tokens"] += stats.get("valid_tokens", 0)
    return totals


def _priority_score(priority: str | None) -> int:
    order = {"baixa": 1, "media": 2, "alta": 3, "critica": 4}
    return order.get((priority or "").strip().lower(), 2)


def _priority_to_risk(priority: str | None) -> str:
    val = (priority or "").strip().lower()
    return val if val in {"baixa", "media", "alta", "critica"} else "media"


async def send_alert_to_alarm_users(
    db_cur,
    alarme_id: int,
    alert: FCMAlert,
    *,
    deactivate_invalid_tokens: bool = True,
    collect_results: bool = False,
) -> dict[str, Any]:
    """Envia alerta apenas para usuários vinculados a um alarme."""
    # Buscar usuários vinculados ao alarme
    db_cur.execute(
        """
        SELECT DISTINCT au.usuario_id
        FROM alarme_usuarios au
        JOIN alarmes a ON a.id = au.alarme_id
        WHERE au.alarme_id = %s
          AND a.ativo = TRUE
        """,
        (int(alarme_id),),
    )
    users = [str(row[0]) for row in db_cur.fetchall()]
    
    logger.info("[FCM] send_alert_to_alarm_users: alarme_id=%s linked_users=%d", alarme_id, len(users))
    
    if not users:
        logger.warning("[FCM] Alarme %s tem 0 usuários vinculados", alarme_id)
        return {
            "sent": 0,
            "failed": 0,
            "invalid": 0,
            "users": 0,
            "linked_users": 0,
            "users_found": 0,
            "users_with_tokens": 0,
            "valid_tokens": 0,
            "tokens_attempted": 0,
        }

    totals = {
        "sent": 0,
        "failed": 0,
        "invalid": 0,
        "users": len(users),
        "linked_users": len(users),
        "users_found": len(users),
        "users_with_tokens": 0,
        "valid_tokens": 0,
        "tokens_attempted": 0,
    }
    
    aggregated_resultados: list[dict[str, Any]] = []
    aggregated_token_ids: list[int] = []

    for user_id in users:
        stats = await send_alert_to_user_tokens(
            db_cur,
            user_id,
            alert,
            deactivate_invalid_tokens=deactivate_invalid_tokens,
            collect_results=collect_results,
        )
        valid_tokens = int(stats.get("valid_tokens") or 0)

        if valid_tokens > 0:
            totals["users_with_tokens"] += 1
            logger.info("[FCM] alarme_id=%s user_id=%s valid_tokens=%d", alarme_id, user_id, valid_tokens)
        else:
            logger.warning("[FCM] alarme_id=%s user_id=%s valid_tokens=0", alarme_id, user_id)

        totals["valid_tokens"] += valid_tokens
        totals["tokens_attempted"] += valid_tokens
        totals["sent"] += stats["sent"]
        totals["failed"] += stats["failed"]
        totals["invalid"] += stats["invalid"]
        if collect_results:
            aggregated_resultados.extend(stats.get("resultados", []))
            aggregated_token_ids.extend([int(tid) for tid in stats.get("token_ids", [])])
    
    logger.info(
        "[FCM] send_alert_to_alarm_users resultado: alarme_id=%s linked_users=%d users_with_tokens=%d valid_tokens=%d sent=%d failed=%d invalid=%d",
        alarme_id,
        totals["linked_users"],
        totals["users_with_tokens"],
        totals["valid_tokens"],
        totals["sent"],
        totals["failed"],
        totals["invalid"],
    )
    
    if collect_results:
        totals["token_ids"] = sorted(set(aggregated_token_ids))
        totals["resultados"] = aggregated_resultados
        totals["tokens_encontrados"] = len(totals["token_ids"])
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
    """Dispara push apenas para usuários vinculados a alarmes ativos da(s) lista(s) da placa."""
    logger.info(
        "[FCM] send_alert_for_detected_plate INÍCIO event_id=%s plate_recebida=%s",
        event_id,
        plate,
    )
    plate_normalized = normalize_plate(plate)
    logger.info(
        "[FCM] Placa normalizada event_id=%s plate_normalizada=%s",
        event_id,
        plate_normalized,
    )
    if not plate_normalized:
        logger.warning(
            "[FCM] Auto-alerta ignorado event_id=%s: placa vazia/invalidada após normalização",
            event_id,
        )
        return False

    try:
        logger.info(
            "[FCM] Executando query match event_id=%s plate_normalized=%s",
            event_id,
            plate_normalized,
        )
        db_cur.execute(
            """
            SELECT a.id AS alarme_id,
                   a.nome AS alarme_nome,
                   a.prioridade,
                   vl.id AS lista_id,
                   vl.name AS lista_nome,
                   au.usuario_id
            FROM vehicle_list_items vli
            JOIN vehicle_lists vl ON vl.id = vli.list_id
            JOIN alarme_listas al ON al.lista_id = vl.id
            JOIN alarmes a ON a.id = al.alarme_id AND a.ativo = TRUE
            JOIN alarme_usuarios au ON au.alarme_id = a.id
            WHERE REGEXP_REPLACE(UPPER(vli.plate), '[^A-Z0-9]', '', 'g') = %s
            """,
            (plate_normalized,),
        )
        rows = db_cur.fetchall()
        logger.info(
            "[FCM] Query retornou %s rows para event_id=%s plate=%s",
            len(rows),
            event_id,
            plate_normalized,
        )

        if not rows:
            logger.warning(
                "[FCM] NENHUM MATCH event_id=%s plate=%s - placa não está em lista+alarme ativo ou não há usuários vinculados",
                event_id,
                plate_normalized,
            )
            return False

        alarm_ids = sorted({int(r[0]) for r in rows})
        user_ids = sorted({str(r[5]) for r in rows})
        logger.info(
            "[FCM] Match real placa=%s alarmes_ativos=%s usuarios_vinculados=%s",
            plate_normalized,
            alarm_ids,
            user_ids,
        )

        alarms: dict[int, dict[str, Any]] = {}
        users: dict[str, dict[str, Any]] = {}
        for alarme_id, alarme_nome, prioridade, _lista_id, lista_nome, usuario_id in rows:
            aid = int(alarme_id)
            uid = str(usuario_id)
            pr = (prioridade or "media").strip().lower()

            if aid not in alarms:
                alarms[aid] = {
                    "nome": str(alarme_nome or f"Alarme {aid}"),
                    "prioridade": pr,
                    "listas": set(),
                }
            alarms[aid]["listas"].add(str(lista_nome or "Lista"))

            if uid not in users:
                users[uid] = {"max_priority": pr, "alarm_names": set(), "list_names": set()}
            if _priority_score(pr) > _priority_score(users[uid]["max_priority"]):
                users[uid]["max_priority"] = pr
            users[uid]["alarm_names"].add(str(alarme_nome or f"Alarme {aid}"))
            users[uid]["list_names"].add(str(lista_nome or "Lista"))

        sent_total = 0
        failed_total = 0
        invalid_total = 0

        for uid, meta in users.items():
            alarm_names = sorted(meta["alarm_names"])
            list_names = sorted(meta["list_names"])
            risk_level = _priority_to_risk(meta["max_priority"])
            target_name = (
                f"{', '.join(alarm_names)} | Lista(s): {', '.join(list_names)}"
                if alarm_names or list_names
                else plate_normalized
            )

            alert = FCMAlert(
                plate=plate_normalized,
                target_name=target_name,
                camera_name=camera_name or "Camera desconhecida",
                detected_at=datetime.now(timezone.utc).isoformat(),
                image_url=image_url or "",
                event_id=str(event_id),
                city=city or "N/A",
                risk_level=risk_level,
                alert_type="critical_alert",
            )

            logger.info(
                "[FCM] Enviando push event_id=%s user_id=%s plate=%s",
                event_id,
                uid,
                plate_normalized,
            )
            stats = await send_alert_to_user_tokens(db_cur, uid, alert)
            sent_total += stats["sent"]
            failed_total += stats["failed"]
            invalid_total += stats["invalid"]
            logger.info(
                "[FCM] Push resultado event_id=%s user_id=%s valid_tokens=%s sent=%s failed=%s invalid=%s",
                event_id,
                uid,
                stats.get("valid_tokens", 0),
                stats["sent"],
                stats["failed"],
                stats["invalid"],
            )

            logger.info(
                "[FCM] Inserindo alertas_criticos event_id=%s user_id=%s plate=%s",
                event_id,
                uid,
                plate_normalized,
            )
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
                    uid,
                    None,
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
                "[FCM] alertas_criticos INSERIDO com sucesso event_id=%s user_id=%s",
                event_id,
                uid,
            )

        logger.info(
            "[FCM] Auto-alerta COMPLETO event_id=%s plate=%s cam=%s conf=%.2f users=%s sent=%s failed=%s invalid=%s",
            event_id,
            plate_normalized,
            camera_name,
            confidence,
            len(users),
            sent_total,
            failed_total,
            invalid_total,
        )
        return sent_total > 0
    except Exception as exc:
        logger.exception("[FCM] Erro no auto-alerta da placa %s: %s", plate_normalized, exc)
        return False
