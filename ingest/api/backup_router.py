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

        backup_dir = Path(os.getenv("BACKUP_DIR", "/backup/postgres"))
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

        backup_dir = Path(os.getenv("BACKUP_DIR", "/backup/postgres"))
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

        backup_dir = Path(os.getenv("BACKUP_DIR", "/backup/postgres"))
        log_path = Path(os.getenv("BACKUP_LOG_PATH", str(backup_dir / "backup.log")))
        backup_dir.mkdir(parents=True, exist_ok=True)

        timeout = int(os.getenv("BACKUP_RUN_TIMEOUT", "600"))
        backup_file = _run_pg_dump(backup_dir, timeout)

        log_line = f"Backup criado com sucesso em: {backup_file}\n"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log_f:
            log_f.write(log_line)

        return {"status": "ok", "file": str(backup_file)}

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


def _run_pg_dump(backup_dir: Path, timeout: int) -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_file = backup_dir / f"backup_{timestamp}.sql"

    pg_host = os.getenv("POSTGRES_HOST", "postgres")
    pg_port = os.getenv("POSTGRES_PORT", "5432")
    pg_user = os.getenv("POSTGRES_USER", "monitor_user")
    pg_db = os.getenv("POSTGRES_DB", "monitor")
    pg_password = os.getenv("POSTGRES_PASSWORD", "")

    env = os.environ.copy()
    if pg_password:
        env["PGPASSWORD"] = pg_password

    cmd = [
        "pg_dump",
        "-h",
        pg_host,
        "-p",
        str(pg_port),
        "-U",
        pg_user,
        "-d",
        pg_db,
    ]

    try:
        with backup_file.open("w", encoding="utf-8") as out_f:
            result = subprocess.run(
                cmd,
                stdout=out_f,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
                env=env,
            )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Backup em execucao por muito tempo")

    if result.returncode != 0:
        detail = (result.stderr or "Falha ao executar backup").strip()
        raise HTTPException(status_code=500, detail=detail[:300])

    _prune_old_backups(backup_dir, keep=7)
    return backup_file


def _prune_old_backups(backup_dir: Path, keep: int) -> None:
    candidates = sorted(
        (p for p in backup_dir.glob("backup_*.sql") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old_file in candidates[keep:]:
        try:
            old_file.unlink()
        except OSError:
            continue
