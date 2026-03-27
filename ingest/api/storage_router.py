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


def _read_mount_index_from_proc(mount_file: Path, pseudo_fs: set[str]) -> list[dict[str, str]]:
    mounts: list[dict[str, str]] = []
    if not mount_file.exists():
        return mounts
    with mount_file.open("r", encoding="utf-8", errors="ignore") as fh:
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
    return mounts


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

    host_root = Path(os.environ.get("HOST_ROOT", "/host"))
    if host_root.exists():
        host_mounts = _read_mount_index_from_proc(host_root / "proc/mounts", pseudo_fs)
        if host_mounts:
            host_mounts.sort(key=lambda item: len(item["mount_point"]), reverse=True)
            return host_mounts

    # Try df -PT when host mounts are not available.
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
        mounts.extend(_read_mount_index_from_proc(Path("/proc/mounts"), pseudo_fs))
    mounts.sort(key=lambda item: len(item["mount_point"]), reverse=True)
    return mounts


def _match_mount_info(target_path: Path, mount_index: list[dict[str, str]]) -> dict[str, str]:
    target = str(target_path.resolve())
    for item in mount_index:
        mount_point = item["mount_point"]
        if target == mount_point or target.startswith(mount_point.rstrip("/") + "/"):
            return item
    return {"mount_point": target, "device": "desconhecido", "fs_type": "desconhecido"}


def _resolve_host_path(path: Path) -> Path | None:
    host_root = Path(os.environ.get("HOST_ROOT", "/host"))
    if not host_root.exists():
        return None
    rel = str(path.resolve()).lstrip("/")
    host_path = host_root / rel
    return host_path if host_path.exists() else None


def _group_mounts_by_device(mount_index: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    device_map: dict[str, dict[str, Any]] = {}
    for item in mount_index:
        device = (item.get("device") or "").strip()
        mount_point = (item.get("mount_point") or "").strip()
        if not device or not mount_point:
            continue
        if device in ("overlay", "tmpfs", "udev"):
            continue
        entry = device_map.setdefault(
            device,
            {
                "fs_type": item.get("fs_type"),
                "mount_points": [],
            },
        )
        entry["mount_points"].append(mount_point)
    return device_map


def _list_storage_mounts(storage_dirs: dict[str, Path]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    mount_index = _read_mount_index()
    device_map = _group_mounts_by_device(mount_index)
    for device, info in device_map.items():
        mount_points = sorted(info.get("mount_points") or [], key=len)
        if not mount_points:
            continue
        primary_mount = mount_points[0]
        usage_path = _resolve_host_path(Path(primary_mount)) or Path(primary_mount)
        try:
            usage = shutil.disk_usage(usage_path)
        except Exception:
            usage = None
        items.append(
            {
                "key": f"device:{device}",
                "label": f"Disco {device}",
                "mount_point": primary_mount,
                "mount_points": mount_points,
                "device": device,
                "fs_type": info.get("fs_type"),
                "backing_mount": primary_mount,
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
