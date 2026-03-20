"""Audit trail and online presence helpers for administrative monitoring."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable, Optional

from fastapi import Request
from psycopg2.extras import Json

from rbac import normalize_role

logger = logging.getLogger(__name__)

ONLINE_WINDOW_SECONDS = 120
_LOCAL_TZ_SQL = "America/Sao_Paulo"


def _clip_text(value: Any, max_len: int = 255) -> str:
    return str(value or "").strip()[:max_len]


def _client_ip(request: Request) -> str:
    forwarded = _clip_text(request.headers.get("x-forwarded-for"), 200)
    if forwarded:
        return _clip_text(forwarded.split(",", 1)[0], 80)
    return _clip_text(getattr(request.client, "host", ""), 80)


def _user_agent(request: Request) -> str:
    return _clip_text(request.headers.get("user-agent"), 300)


def _page_key(value: Any) -> str:
    return _clip_text(value, 120)


def _page_label(value: Any) -> str:
    return _clip_text(value, 160)


def _page_path(value: Any) -> str:
    return _clip_text(value, 240)


def _activity_type_label(activity_type: str | None) -> str:
    mapping = {
        "login": "Login",
        "page_view": "Pagina",
        "logout": "Logout",
        "produtividade_reset": "Reset Produtividade",
        "produtividade_reset_negado": "Reset Negado",
    }
    return mapping.get(str(activity_type or "").strip().lower(), "Atividade")


def _interval_sql() -> str:
    return "(%s || ' seconds')::interval"


def _upsert_session(
    cur,
    *,
    session_id: str,
    username: str,
    full_name: str,
    role: str,
    page_key: str = "",
    page_label: str = "",
    page_path: str = "",
    ip_address: str = "",
    user_agent: str = "",
) -> None:
    cur.execute(
        """
        INSERT INTO admin_user_sessions (
            session_id,
            username,
            full_name,
            role,
            login_at,
            last_seen_at,
            last_page_key,
            last_page_label,
            last_page_path,
            ip_address,
            user_agent,
            is_online
        )
        VALUES (%s, %s, %s, %s, NOW(), NOW(), %s, %s, %s, %s, %s, TRUE)
        ON CONFLICT (session_id) DO UPDATE SET
            username = EXCLUDED.username,
            full_name = EXCLUDED.full_name,
            role = EXCLUDED.role,
            last_seen_at = NOW(),
            logout_at = NULL,
            is_online = TRUE,
            last_page_key = COALESCE(NULLIF(EXCLUDED.last_page_key, ''), admin_user_sessions.last_page_key),
            last_page_label = COALESCE(NULLIF(EXCLUDED.last_page_label, ''), admin_user_sessions.last_page_label),
            last_page_path = COALESCE(NULLIF(EXCLUDED.last_page_path, ''), admin_user_sessions.last_page_path),
            ip_address = COALESCE(NULLIF(EXCLUDED.ip_address, ''), admin_user_sessions.ip_address),
            user_agent = COALESCE(NULLIF(EXCLUDED.user_agent, ''), admin_user_sessions.user_agent)
        """,
        (
            session_id,
            username,
            full_name,
            role,
            page_key,
            page_label,
            page_path,
            ip_address,
            user_agent,
        ),
    )


def _insert_activity(
    cur,
    *,
    session_id: str,
    username: str,
    full_name: str,
    role: str,
    activity_type: str,
    page_key: str = "",
    page_label: str = "",
    page_path: str = "",
    ip_address: str = "",
    user_agent: str = "",
    details: Optional[dict[str, Any]] = None,
) -> None:
    cur.execute(
        """
        INSERT INTO admin_user_activity_log (
            session_id,
            username,
            full_name,
            role,
            activity_type,
            page_key,
            page_label,
            page_path,
            details,
            ip_address,
            user_agent
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            session_id,
            username,
            full_name,
            role,
            _clip_text(activity_type, 40),
            page_key,
            page_label,
            page_path,
            Json(details or {}),
            ip_address,
            user_agent,
        ),
    )


def start_user_session(
    conn_factory: Callable[[], Any],
    *,
    request: Request,
    username: str,
    full_name: str,
    role: str,
    session_id: str | None = None,
) -> str:
    sid = _clip_text(session_id, 120) or uuid.uuid4().hex
    safe_role = normalize_role(role)
    ip_address = _client_ip(request)
    user_agent = _user_agent(request)

    with conn_factory() as conn:
        with conn.cursor() as cur:
            _upsert_session(
                cur,
                session_id=sid,
                username=username,
                full_name=full_name,
                role=safe_role,
                page_key="login",
                page_label="Login",
                page_path="/login",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            _insert_activity(
                cur,
                session_id=sid,
                username=username,
                full_name=full_name,
                role=safe_role,
                activity_type="login",
                page_key="login",
                page_label="Login",
                page_path="/login",
                ip_address=ip_address,
                user_agent=user_agent,
                details={"source": "auth_login"},
            )

    return sid


def heartbeat_user_session(
    conn_factory: Callable[[], Any],
    *,
    request: Request,
    username: str,
    full_name: str,
    role: str,
    session_id: str,
    page_key: str = "",
    page_label: str = "",
    page_path: str = "",
) -> str:
    sid = _clip_text(session_id, 120) or ("legacy-" + uuid.uuid4().hex)
    with conn_factory() as conn:
        with conn.cursor() as cur:
            _upsert_session(
                cur,
                session_id=sid,
                username=username,
                full_name=full_name,
                role=normalize_role(role),
                page_key=_page_key(page_key),
                page_label=_page_label(page_label),
                page_path=_page_path(page_path),
                ip_address=_client_ip(request),
                user_agent=_user_agent(request),
            )
    return sid


def track_user_page(
    conn_factory: Callable[[], Any],
    *,
    request: Request,
    username: str,
    full_name: str,
    role: str,
    session_id: str,
    page_key: str,
    page_label: str,
    page_path: str,
) -> str:
    sid = _clip_text(session_id, 120) or ("legacy-" + uuid.uuid4().hex)
    safe_role = normalize_role(role)
    safe_page_key = _page_key(page_key)
    safe_page_label = _page_label(page_label)
    safe_page_path = _page_path(page_path)
    ip_address = _client_ip(request)
    user_agent = _user_agent(request)

    with conn_factory() as conn:
        with conn.cursor() as cur:
            _upsert_session(
                cur,
                session_id=sid,
                username=username,
                full_name=full_name,
                role=safe_role,
                page_key=safe_page_key,
                page_label=safe_page_label,
                page_path=safe_page_path,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            _insert_activity(
                cur,
                session_id=sid,
                username=username,
                full_name=full_name,
                role=safe_role,
                activity_type="page_view",
                page_key=safe_page_key,
                page_label=safe_page_label,
                page_path=safe_page_path,
                ip_address=ip_address,
                user_agent=user_agent,
                details={"kind": "spa_navigation"},
            )

    return sid


def track_user_activity(
    conn_factory: Callable[[], Any],
    *,
    request: Request,
    username: str,
    full_name: str,
    role: str,
    session_id: str,
    activity_type: str,
    page_key: str = "",
    page_label: str = "",
    page_path: str = "",
    details: Optional[dict[str, Any]] = None,
) -> str:
    sid = _clip_text(session_id, 120) or ("legacy-" + uuid.uuid4().hex)
    safe_role = normalize_role(role)
    safe_page_key = _page_key(page_key)
    safe_page_label = _page_label(page_label)
    safe_page_path = _page_path(page_path)
    ip_address = _client_ip(request)
    user_agent = _user_agent(request)

    with conn_factory() as conn:
        with conn.cursor() as cur:
            _upsert_session(
                cur,
                session_id=sid,
                username=username,
                full_name=full_name,
                role=safe_role,
                page_key=safe_page_key,
                page_label=safe_page_label,
                page_path=safe_page_path,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            _insert_activity(
                cur,
                session_id=sid,
                username=username,
                full_name=full_name,
                role=safe_role,
                activity_type=activity_type,
                page_key=safe_page_key,
                page_label=safe_page_label,
                page_path=safe_page_path,
                ip_address=ip_address,
                user_agent=user_agent,
                details=details or {},
            )

    return sid


def finish_user_session(
    conn_factory: Callable[[], Any],
    *,
    request: Request,
    username: str,
    full_name: str,
    role: str,
    session_id: str,
    page_key: str = "",
    page_label: str = "",
    page_path: str = "",
) -> str:
    sid = _clip_text(session_id, 120) or ("legacy-" + uuid.uuid4().hex)
    safe_role = normalize_role(role)
    safe_page_key = _page_key(page_key)
    safe_page_label = _page_label(page_label)
    safe_page_path = _page_path(page_path)
    ip_address = _client_ip(request)
    user_agent = _user_agent(request)

    with conn_factory() as conn:
        with conn.cursor() as cur:
            _upsert_session(
                cur,
                session_id=sid,
                username=username,
                full_name=full_name,
                role=safe_role,
                page_key=safe_page_key,
                page_label=safe_page_label,
                page_path=safe_page_path,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            cur.execute(
                """
                UPDATE admin_user_sessions
                SET is_online = FALSE,
                    logout_at = NOW(),
                    last_seen_at = NOW(),
                    last_page_key = COALESCE(NULLIF(%s, ''), last_page_key),
                    last_page_label = COALESCE(NULLIF(%s, ''), last_page_label),
                    last_page_path = COALESCE(NULLIF(%s, ''), last_page_path)
                WHERE session_id = %s
                """,
                (safe_page_key, safe_page_label, safe_page_path, sid),
            )
            _insert_activity(
                cur,
                session_id=sid,
                username=username,
                full_name=full_name,
                role=safe_role,
                activity_type="logout",
                page_key=safe_page_key,
                page_label=safe_page_label,
                page_path=safe_page_path,
                ip_address=ip_address,
                user_agent=user_agent,
                details={"source": "manual_logout"},
            )

    return sid


def get_admin_activity_overview(conn_factory: Callable[[], Any]) -> dict[str, Any]:
    with conn_factory() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM (
                    SELECT DISTINCT username
                    FROM admin_user_sessions
                    WHERE is_online = TRUE
                      AND last_seen_at >= NOW() - {_interval_sql()}
                ) q
                """,
                (ONLINE_WINDOW_SECONDS,),
            )
            online_users = int(cur.fetchone()[0] or 0)

            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM admin_user_sessions
                WHERE is_online = TRUE
                  AND last_seen_at >= NOW() - {_interval_sql()}
                """,
                (ONLINE_WINDOW_SECONDS,),
            )
            active_sessions = int(cur.fetchone()[0] or 0)

            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM admin_user_activity_log
                WHERE activity_type = 'login'
                  AND (created_at AT TIME ZONE '{_LOCAL_TZ_SQL}')::date =
                      (NOW() AT TIME ZONE '{_LOCAL_TZ_SQL}')::date
                """
            )
            logins_today = int(cur.fetchone()[0] or 0)

            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM admin_user_activity_log
                WHERE activity_type = 'page_view'
                  AND (created_at AT TIME ZONE '{_LOCAL_TZ_SQL}')::date =
                      (NOW() AT TIME ZONE '{_LOCAL_TZ_SQL}')::date
                """
            )
            page_views_today = int(cur.fetchone()[0] or 0)

            cur.execute("SELECT MAX(created_at) FROM admin_user_activity_log")
            last_activity_at = cur.fetchone()[0]

    return {
        "online_users": online_users,
        "active_sessions": active_sessions,
        "logins_today": logins_today,
        "page_views_today": page_views_today,
        "last_activity_at": last_activity_at.isoformat() if last_activity_at else None,
        "online_threshold_seconds": ONLINE_WINDOW_SECONDS,
    }


def get_online_users(conn_factory: Callable[[], Any]) -> list[dict[str, Any]]:
    with conn_factory() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    session_id,
                    username,
                    full_name,
                    role,
                    login_at,
                    last_seen_at,
                    last_page_key,
                    last_page_label,
                    last_page_path,
                    ip_address
                FROM admin_user_sessions
                WHERE is_online = TRUE
                  AND last_seen_at >= NOW() - {_interval_sql()}
                ORDER BY last_seen_at DESC, login_at DESC
                """,
                (ONLINE_WINDOW_SECONDS,),
            )
            rows = cur.fetchall()

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        username = row[1]
        if username not in grouped:
            grouped[username] = {
                "session_id": row[0],
                "username": username,
                "full_name": row[2] or username,
                "role": normalize_role(row[3]),
                "login_at": row[4].isoformat() if row[4] else None,
                "last_seen_at": row[5].isoformat() if row[5] else None,
                "last_page_key": row[6] or "",
                "last_page_label": row[7] or "",
                "last_page_path": row[8] or "",
                "ip_address": row[9] or "",
                "active_sessions": 1,
            }
        else:
            grouped[username]["active_sessions"] += 1

    return list(grouped.values())


def get_recent_activity(conn_factory: Callable[[], Any], limit: int = 80) -> list[dict[str, Any]]:
    safe_limit = max(1, min(200, int(limit)))
    with conn_factory() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    session_id,
                    username,
                    full_name,
                    role,
                    activity_type,
                    page_key,
                    page_label,
                    page_path,
                    ip_address,
                    created_at
                FROM admin_user_activity_log
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (safe_limit,),
            )
            rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "session_id": row[1],
            "username": row[2],
            "full_name": row[3] or row[2],
            "role": normalize_role(row[4]),
            "activity_type": row[5],
            "activity_label": _activity_type_label(row[5]),
            "page_key": row[6] or "",
            "page_label": row[7] or "",
            "page_path": row[8] or "",
            "ip_address": row[9] or "",
            "created_at": row[10].isoformat() if row[10] else None,
        }
        for row in rows
    ]
