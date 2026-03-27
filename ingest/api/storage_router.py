import os
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse


def _safe_file_path(base_dir: Path, file_path: str) -> Path:
    base_dir = base_dir.resolve()
    target = (base_dir / file_path).resolve()
    if not target.is_relative_to(base_dir):
        raise HTTPException(status_code=404, detail="arquivo nao encontrado")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="arquivo nao encontrado")
    return target


def _read_mount_index() -> list[dict[str, str]]:
    mounts: list[dict[str, str]] = []
    pseudo_fs = {
        "proc",
        "sysfs",
        "tmpfs",
        "devtmpfs",
        "devpts",
        "overlay",
        "squashfs",
        "cgroup",
        "cgroup2",
        "mqueue",
        "rpc_pipefs",
        "tracefs",
        "securityfs",
        "pstore",
        "autofs",
        "debugfs",
        "configfs",
        "fusectl",
    }

    # Tenta usar df -PT (mais confiável em containers)
    try:
        output = subprocess.check_output(["df", "-PT"], text=True, stderr=subprocess.DEVNULL)
        for line in output.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 7:
                continue
            device, fs_type, mount_point = parts[0], parts[1], parts[6]
            if fs_type in pseudo_fs:
                continue
            if device in ("overlay", "tmpfs", "udev"):
                continue
            mounts.append(
                {
                    "mount_point": mount_point,
                    "device": device,
                    "fs_type": fs_type,
                }
            )
    except Exception:
        mount_file = "/proc/mounts" if os.path.exists("/proc/mounts") else None
        if mount_file:
            with open(mount_file, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    parts = line.split()
                    if len(parts) < 3:
                        continue
                    device, mount_point, fs_type = parts[0], parts[1], parts[2]
                    mount_point = mount_point.replace("\\040", " ")
                    if fs_type in pseudo_fs:
                        continue
                    if device in ("overlay", "tmpfs", "udev"):
                        continue
                    mounts.append(
                        {
                            "mount_point": mount_point,
                            "device": device,
                            "fs_type": fs_type,
                        }
                    )
    mounts.sort(key=lambda item: len(item["mount_point"]), reverse=True)
    return mounts


def _match_mount_info(target_path: Path, mount_index: list[dict[str, str]]) -> dict[str, str]:
    target = str(target_path.resolve())
    for item in mount_index:
        mount_point = item["mount_point"]
        if target == mount_point or target.startswith(mount_point.rstrip("/") + "/"):
            return item
    return {"mount_point": target, "device": "desconhecido", "fs_type": "desconhecido"}


def _list_storage_mounts(storage_dirs: dict[str, Path]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    mount_index = _read_mount_index()
    seen_devices: set[str] = set()
    labels = {
        "event_images_dir": "Imagens de eventos",
        "abordagem_images_dir": "Imagens de abordagens",
        "metadata_dir": "Metadados",
    }
    for key, path in storage_dirs.items():
        resolved = path.resolve()
        path_key = str(resolved)
        if path_key in seen:
            continue
        seen.add(path_key)
        try:
            usage = shutil.disk_usage(resolved)
        except Exception:
            usage = None
        mount_info = _match_mount_info(resolved, mount_index)
        items.append(
            {
                "key": key,
                "label": labels.get(key, key),
                "mount_point": str(resolved),
                "device": mount_info.get("device"),
                "fs_type": mount_info.get("fs_type"),
                "backing_mount": mount_info.get("mount_point"),
                "total_gb": round((usage.total / (1024**3)), 2) if usage else None,
                "used_gb": round((usage.used / (1024**3)), 2) if usage else None,
                "free_gb": round((usage.free / (1024**3)), 2) if usage else None,
                "used_percent": round(((usage.used / usage.total) * 100), 2)
                if usage and usage.total
                else None,
            }
        )
    # Adiciona todos os pontos de montagem do Linux para exibir no gráfico
    for mount in mount_index:
        mount_point = mount.get("mount_point")
        if not mount_point:
            continue
        device = mount.get("device") or ""
        if device and device in seen_devices:
            continue
        if mount_point in seen:
            continue
        seen.add(mount_point)
        if device:
            seen_devices.add(device)
        try:
            usage = shutil.disk_usage(mount_point)
        except Exception:
            usage = None
        items.append(
            {
                "key": f"mount:{mount_point}",
                "label": f"Disco {mount_point}",
                "mount_point": mount_point,
                "device": device or "desconhecido",
                "fs_type": mount.get("fs_type"),
                "backing_mount": mount_point,
                "total_gb": round((usage.total / (1024**3)), 2) if usage else None,
                "used_gb": round((usage.used / (1024**3)), 2) if usage else None,
                "free_gb": round((usage.free / (1024**3)), 2) if usage else None,
                "used_percent": round(((usage.used / usage.total) * 100), 2)
                if usage and usage.total
                else None,
            }
        )
    items.sort(key=lambda item: item["label"])
    return items


def build_storage_router(
    conn_factory: Callable[[], Any],
    require_auth_fn: Callable[[Request], Any],
    assert_admin_fn: Callable[[Request, str], Any],
    resolve_storage_path_fn: Callable[[str, Path], Path],
    ensure_storage_dir_fn: Callable[[Path, str], None],
    get_storage_dir_fn: Callable[[str], Path],
    default_storage_paths_fn: Callable[[], dict[str, Path]],
    set_storage_cache_fn: Callable[[dict[str, str]], None] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["storage"])

    @router.get("/api/storage/settings")
    def get_storage_settings(request: Request):
        require_auth_fn(request)
        assert_admin_fn(request, "Apenas administradores podem visualizar os caminhos de armazenamento")
        defaults = default_storage_paths_fn()
        values = {key: str(path) for key, path in defaults.items()}
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT key, path FROM storage_settings")
                for key, path in cur.fetchall():
                    if key in values and path:
                        values[key] = str(resolve_storage_path_fn(path, defaults[key]))
        return values

    @router.put("/api/storage/settings")
    async def update_storage_settings(request: Request):
        assert_admin_fn(request, "Apenas administradores podem alterar os caminhos de armazenamento")
        data = await request.json()
        defaults = default_storage_paths_fn()
        next_values: dict[str, str] = {}
        for key, default_path in defaults.items():
            raw_value = str(data.get(key) or "").strip()
            if not raw_value:
                raise HTTPException(status_code=400, detail=f"{key} e obrigatorio")
            resolved = resolve_storage_path_fn(raw_value, default_path)
            ensure_storage_dir_fn(resolved, key)
            next_values[key] = str(resolved)

        with conn_factory() as conn:
            with conn.cursor() as cur:
                for key, path in next_values.items():
                    cur.execute(
                        """
                        INSERT INTO storage_settings (key, path, updated_at)
                        VALUES (%s, %s, NOW())
                        ON CONFLICT (key) DO UPDATE SET
                            path = EXCLUDED.path,
                            updated_at = NOW()
                        """,
                        (key, path),
                    )
        if set_storage_cache_fn:
            set_storage_cache_fn(next_values)
        return {"ok": True, "settings": next_values}

    @router.get("/api/storage/volumes")
    def list_storage_volumes(request: Request):
        require_auth_fn(request)
        assert_admin_fn(request, "Apenas administradores podem visualizar os discos do servidor")
        storage_dirs = {key: get_storage_dir_fn(key) for key in default_storage_paths_fn().keys()}
        return {"items": _list_storage_mounts(storage_dirs)}

    @router.get("/uploads/{file_path:path}", include_in_schema=False)
    async def serve_upload(file_path: str):
        return FileResponse(_safe_file_path(get_storage_dir_fn("event_images_dir"), file_path))

    @router.get("/abordados/{file_path:path}", include_in_schema=False)
    async def serve_abordado(file_path: str):
        return FileResponse(_safe_file_path(get_storage_dir_fn("abordagem_images_dir"), file_path))

    return router
