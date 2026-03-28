import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Request


def build_backup_router(
    require_auth_fn: Callable[[Request], Any],
    assert_admin_fn: Callable[[Request, str], Any],
) -> APIRouter:
    router = APIRouter(tags=["backup"])

    @router.get("/api/backup/status")
    def backup_status(request: Request):
        require_auth_fn(request)
        assert_admin_fn(request, "Apenas administradores podem visualizar o status de backup")

        raw_path = os.getenv("BACKUP_LOG_PATH", "/host/backup/postgres/backup.log")
        log_path = Path(raw_path)
        if not log_path.exists():
            return {
                "status": "not_configured",
                "detail": "Arquivo de log nao encontrado",
                "path": str(log_path),
            }

        stat = log_path.stat()
        last_backup = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        age = datetime.now(timezone.utc) - last_backup
        max_age = timedelta(hours=int(os.getenv("BACKUP_MAX_AGE_HOURS", "36")))

        return {
            "status": "ok" if age <= max_age else "stale",
            "path": str(log_path),
            "size_bytes": stat.st_size,
            "last_backup": last_backup.isoformat().replace("+00:00", "Z"),
            "age_hours": round(age.total_seconds() / 3600, 2),
            "max_age_hours": round(max_age.total_seconds() / 3600, 2),
        }

    return router
