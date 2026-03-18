from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.responses import RedirectResponse


def build_core_router(
    static_dir: Any,
    catchall_handler_fn: Callable[[Request], Any],
) -> APIRouter:
    router = APIRouter(tags=["core"])

    @router.get("/", include_in_schema=False)
    def root():
        return RedirectResponse(url="/dashboard")

    @router.get("/dashboard", include_in_schema=False)
    def dashboard_page():
        dashboard_file = static_dir / "dashboard.html"
        if dashboard_file.exists():
            return FileResponse(dashboard_file)
        return RedirectResponse(url="/")

    @router.get("/login", include_in_schema=False)
    def login_page():
        login_file = static_dir / "login.html"
        if login_file.exists():
            return FileResponse(login_file)
        return PlainTextResponse(
            "Arquivo static/login.html não encontrado.\nColoque sua tela de login em ingest/static/login.html",
            status_code=404,
            media_type="text/plain; charset=utf-8",
        )

    @router.get("/health")
    def health():
        return {"status": "ok"}

    @router.api_route(
        "/catchall",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=True,
        tags=["debug"],
        summary="Catch-all público (sem /api)",
    )
    async def catchall_root(request: Request):
        return await catchall_handler_fn(request)

    return router
