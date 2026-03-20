from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request

from rbac import assert_admin, require_auth
from services.admin_activity_service import (
    finish_user_session,
    get_admin_activity_overview,
    get_online_users,
    get_recent_activity,
    heartbeat_user_session,
    track_user_page,
)


def build_admin_activity_router(conn_factory: Callable[[], Any]) -> APIRouter:
    router = APIRouter(tags=["admin-activity"])

    def _current_user(request: Request) -> tuple[str, str, str]:
        user = require_auth(request)
        return (
            str(user.get("sub") or "").strip(),
            str(user.get("name") or user.get("sub") or "").strip(),
            str(user.get("role") or "").strip(),
        )

    def _session_id(request: Request, data: dict[str, Any]) -> str:
        sid = request.headers.get("X-BPFRON-Session") or data.get("session_id") or ""
        sid = str(sid).strip()
        if not sid:
            raise HTTPException(status_code=400, detail="session_id obrigatorio")
        return sid

    async def _safe_json(request: Request) -> dict[str, Any]:
        try:
            data = await request.json()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @router.get("/api/admin/activity/overview")
    async def admin_activity_overview(request: Request):
        assert_admin(request, "Acesso restrito a administradores")
        return get_admin_activity_overview(conn_factory)

    @router.get("/api/admin/activity/online")
    async def admin_activity_online(request: Request):
        assert_admin(request, "Acesso restrito a administradores")
        return {"items": get_online_users(conn_factory)}

    @router.get("/api/admin/activity/recent")
    async def admin_activity_recent(request: Request, limit: int = 80):
        assert_admin(request, "Acesso restrito a administradores")
        return {"items": get_recent_activity(conn_factory, limit=limit)}

    @router.post("/api/admin/activity/heartbeat")
    async def admin_activity_heartbeat(request: Request):
        data = await _safe_json(request)
        username, full_name, role = _current_user(request)
        sid = heartbeat_user_session(
            conn_factory,
            request=request,
            username=username,
            full_name=full_name,
            role=role,
            session_id=_session_id(request, data),
            page_key=data.get("page_key") or "",
            page_label=data.get("page_label") or "",
            page_path=data.get("page_path") or "",
        )
        return {"ok": True, "session_id": sid}

    @router.post("/api/admin/activity/page-view")
    async def admin_activity_page_view(request: Request):
        data = await _safe_json(request)
        username, full_name, role = _current_user(request)
        sid = track_user_page(
            conn_factory,
            request=request,
            username=username,
            full_name=full_name,
            role=role,
            session_id=_session_id(request, data),
            page_key=data.get("page_key") or "",
            page_label=data.get("page_label") or "",
            page_path=data.get("page_path") or "",
        )
        return {"ok": True, "session_id": sid}

    @router.post("/api/admin/activity/logout")
    async def admin_activity_logout(request: Request):
        data = await _safe_json(request)
        username, full_name, role = _current_user(request)
        sid = finish_user_session(
            conn_factory,
            request=request,
            username=username,
            full_name=full_name,
            role=role,
            session_id=_session_id(request, data),
            page_key=data.get("page_key") or "",
            page_label=data.get("page_label") or "",
            page_path=data.get("page_path") or "",
        )
        return {"ok": True, "session_id": sid}

    return router
