import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse


def build_backup_router(
    require_auth_fn: Callable[[Request], Any],
    assert_admin_fn: Callable[[Request, str], Any],
) -> APIRouter:
    router = APIRouter(tags=["backup"])

    @router.get("/api/backup/status")
    def backup_status(request: Request):
        require_auth_fn(request)
        assert_admin_fn(request, "Apenas administradores podem visualizar o status de backup")

        backup_dir = Path(os.getenv("BACKUP_DIR", "/host/backup/postgres"))
        log_path = Path(os.getenv("BACKUP_LOG_PATH", str(backup_dir / "backup.log")))
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

        last_file = _find_latest_backup_file(backup_dir)
        return {
            "status": "ok" if age <= max_age else "stale",
            "path": str(log_path),
            "size_bytes": stat.st_size,
            "last_backup": last_backup.isoformat().replace("+00:00", "Z"),
            "age_hours": round(age.total_seconds() / 3600, 2),
            "max_age_hours": round(max_age.total_seconds() / 3600, 2),
            "backup_dir": str(backup_dir),
            "last_file": str(last_file) if last_file else None,
        }

    @router.get("/api/backup/download")
    def download_backup(request: Request):
        require_auth_fn(request)
        assert_admin_fn(request, "Apenas administradores podem baixar o backup")

        backup_dir = Path(os.getenv("BACKUP_DIR", "/host/backup/postgres"))
        latest = _find_latest_backup_file(backup_dir)
        if not latest:
            raise HTTPException(status_code=404, detail="Nenhum arquivo de backup encontrado")

        return FileResponse(
            latest,
            filename=latest.name,
            media_type="application/octet-stream",
        )

    @router.post("/api/backup/run")
    def run_backup(request: Request):
        require_auth_fn(request)
        assert_admin_fn(request, "Apenas administradores podem executar o backup")

        script_path = Path(os.getenv("BACKUP_SCRIPT_PATH", "/host/dados/backup_postgres.sh"))
        if not script_path.exists():
            raise HTTPException(status_code=404, detail="Script de backup nao encontrado")

        try:
            env = os.environ.copy()
            env.setdefault("DOCKER_HOST", "unix:///var/run/docker.sock")
            env["PATH"] = "/host/usr/bin:/host/bin:/usr/bin:/bin:" + env.get("PATH", "")
            result = subprocess.run(
                ["bash", "-lc", f"bash '{script_path}'"],
                capture_output=True,
                text=True,
                timeout=int(os.getenv("BACKUP_RUN_TIMEOUT", "600")),
                env=env,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="Backup em execucao por muito tempo")

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Falha ao executar backup").strip()
            raise HTTPException(status_code=500, detail=detail[:300])

        return {"status": "ok"}

    return router


def _find_latest_backup_file(backup_dir: Path) -> Path | None:
    if not backup_dir.exists():
        return None
    patterns = ["*.sql", "*.sql.gz", "*.dump", "*.backup", "*.gz"]
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(backup_dir.glob(pattern))
    candidates = [p for p in candidates if p.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)
