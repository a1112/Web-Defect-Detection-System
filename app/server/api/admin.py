from __future__ import annotations

from typing import Any
from pathlib import Path
from datetime import datetime
import asyncio
import json
import os
import platform
import socket
import sys
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.server import deps
from app.server.rbac import manager as rbac_manager
from app.server.net_table import load_map_config, load_map_payload, resolve_net_table_dir

router = APIRouter(tags=["admin"])

REPO_ROOT = Path(__file__).resolve().parents[3]
NGINX_CONFIG_PATH = (
    REPO_ROOT.parent
    / "plugins"
    / "platforms"
    / "windows"
    / "nginx"
    / "conf"
    / "nginx.conf"
)
CONFIGS_DIR = REPO_ROOT / "configs"
TEMPLATE_DIR = CONFIGS_DIR / "template"
CURRENT_DIR = CONFIGS_DIR / "current"
CURRENT_SERVER_CONFIG_PATH = CURRENT_DIR / "server.json"
VERSION_CONFIG_PATH = CONFIGS_DIR / "version.json"
DOWNLOADS_ROOT = REPO_ROOT / "resources" / "downloads"

DOWNLOAD_PLATFORM_SPECS = {
    "windows": {
        "label": "Windows",
        "requirements": ["Windows 10/11", "x64 处理器", "建议 8GB 内存"],
    },
    "linux": {
        "label": "Linux",
        "requirements": ["Ubuntu 20.04+", "x64 处理器", "建议 8GB 内存"],
    },
    "macos": {
        "label": "macOS",
        "requirements": ["macOS 12+", "Apple Silicon / Intel"],
    },
    "android": {
        "label": "Android",
        "requirements": ["Android 10+", "建议 4GB 内存"],
    },
    "ios": {
        "label": "iOS",
        "requirements": ["iOS 15+", "iPhone/iPad"],
    },
}

DOWNLOAD_LABELS = {
    ".exe": "Windows 安装包 (EXE)",
    ".msi": "Windows 安装包 (MSI)",
    ".dmg": "macOS 安装包 (DMG)",
    ".pkg": "macOS 安装包 (PKG)",
    ".appimage": "Linux AppImage",
    ".deb": "Linux DEB",
    ".rpm": "Linux RPM",
    ".apk": "Android APK",
    ".ipa": "iOS IPA",
}


def _format_size(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _parse_version_key(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in version.split("."):
        if part.isdigit():
            parts.append(int(part))
        else:
            head = "".join(ch for ch in part if ch.isdigit())
            parts.append(int(head) if head else 0)
    return tuple(parts or [0])


def _list_versions(root: Path) -> list[str]:
    if not root.exists():
        return []
    versions = [p.name for p in root.iterdir() if p.is_dir()]
    return sorted(versions, key=_parse_version_key, reverse=True)


def _build_download_info() -> dict[str, Any]:
    versions = _list_versions(DOWNLOADS_ROOT)
    flat_files = []
    if DOWNLOADS_ROOT.exists():
        flat_files = [p for p in DOWNLOADS_ROOT.iterdir() if p.is_file()]
    latest_version = versions[0] if versions else ("latest" if flat_files else "")
    if flat_files and latest_version not in versions:
        versions = [latest_version, *versions]
    platforms = []
    latest_timestamp: float | None = None

    for key, spec in DOWNLOAD_PLATFORM_SPECS.items():
        builds: list[dict[str, Any]] = []
        latest_for_platform = ""
        for version in versions:
            version_dir = DOWNLOADS_ROOT / version / key
            if not version_dir.exists():
                continue
            for file_path in sorted(version_dir.iterdir()):
                if not file_path.is_file():
                    continue
                stat = file_path.stat()
                suffix = file_path.suffix.lower()
                label = DOWNLOAD_LABELS.get(suffix, file_path.name)
                builds.append(
                    {
                        "version": version,
                        "label": label,
                        "file_name": file_path.name,
                        "size_bytes": stat.st_size,
                        "size_display": _format_size(stat.st_size),
                        "download_url": f"/config/download/files/{version}/{key}/{quote(file_path.name)}",
                        "released_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d"),
                    }
                )
                if latest_timestamp is None or stat.st_mtime > latest_timestamp:
                    latest_timestamp = stat.st_mtime
            if builds and not latest_for_platform:
                latest_for_platform = version

        if key == "windows" and flat_files and latest_version:
            for file_path in sorted(flat_files):
                stat = file_path.stat()
                suffix = file_path.suffix.lower()
                label = DOWNLOAD_LABELS.get(suffix, file_path.name)
                builds.append(
                    {
                        "version": latest_version,
                        "label": label,
                        "file_name": file_path.name,
                        "size_bytes": stat.st_size,
                        "size_display": _format_size(stat.st_size),
                        "download_url": f"/config/download/files/{quote(file_path.name)}",
                        "released_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d"),
                    }
                )
                if latest_timestamp is None or stat.st_mtime > latest_timestamp:
                    latest_timestamp = stat.st_mtime
            if not latest_for_platform:
                latest_for_platform = latest_version

        platforms.append(
            {
                "key": key,
                "label": spec["label"],
                "supported": len(builds) > 0,
                "requirements": spec["requirements"],
                "builds": builds,
                "latest_version": latest_for_platform or latest_version,
            }
        )

    updated_at = (
        datetime.fromtimestamp(latest_timestamp).strftime("%Y-%m-%d %H:%M:%S")
        if latest_timestamp
        else ""
    )

    return {
        "latest_version": latest_version,
        "history_versions": versions,
        "platforms": platforms,
        "updated_at": updated_at,
        "notes": [],
    }


def _ensure_current_dir() -> Path:
    CURRENT_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("server.json", "map.json", "DefectClass.json"):
        target = CURRENT_DIR / name
        if target.exists():
            continue
        source = TEMPLATE_DIR / name
        if source.exists():
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return CURRENT_DIR


def _read_linux_cpu_times() -> tuple[int, int]:
    with open("/proc/stat", "r", encoding="utf-8") as handle:
        line = handle.readline()
    parts = line.split()
    if len(parts) < 5:
        return 0, 0
    values = [int(value) for value in parts[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values)
    return idle, total


def _get_linux_cpu_percent(sample_seconds: float = 0.1) -> float | None:
    try:
        idle1, total1 = _read_linux_cpu_times()
        time.sleep(sample_seconds)
        idle2, total2 = _read_linux_cpu_times()
        total_delta = total2 - total1
        if total_delta <= 0:
            return None
        idle_delta = idle2 - idle1
        return max(0.0, min(100.0, (1 - idle_delta / total_delta) * 100))
    except OSError:
        return None


def _get_linux_memory() -> tuple[int | None, int | None, float | None]:
    try:
        mem_total = None
        mem_available = None
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal"):
                    mem_total = int(line.split()[1])
                elif line.startswith("MemAvailable"):
                    mem_available = int(line.split()[1])
                if mem_total is not None and mem_available is not None:
                    break
        if mem_total is None or mem_available is None:
            return None, None, None
        used = mem_total - mem_available
        percent = (used / mem_total) * 100 if mem_total else None
        return used * 1024, mem_total * 1024, percent
    except OSError:
        return None, None, None


def _get_linux_network_rate(sample_seconds: float = 0.1) -> tuple[float | None, float | None]:
    def _read_bytes() -> tuple[int, int]:
        rx = 0
        tx = 0
        with open("/proc/net/dev", "r", encoding="utf-8") as handle:
            for line in handle.readlines()[2:]:
                if ":" not in line:
                    continue
                name, stats = line.split(":", 1)
                if name.strip() == "lo":
                    continue
                fields = stats.split()
                if len(fields) >= 16:
                    rx += int(fields[0])
                    tx += int(fields[8])
        return rx, tx

    try:
        rx1, tx1 = _read_bytes()
        time.sleep(sample_seconds)
        rx2, tx2 = _read_bytes()
        rx_rate = (rx2 - rx1) / sample_seconds if rx2 >= rx1 else 0
        tx_rate = (tx2 - tx1) / sample_seconds if tx2 >= tx1 else 0
        return rx_rate, tx_rate
    except OSError:
        return None, None


def _get_resource_metrics() -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "cpu_percent": None,
        "memory_percent": None,
        "memory_total_bytes": None,
        "memory_used_bytes": None,
        "network_rx_bytes_per_sec": None,
        "network_tx_bytes_per_sec": None,
        "notes": [],
    }

    try:
        import psutil  # type: ignore

        metrics["cpu_percent"] = psutil.cpu_percent(interval=0.1)
        vm = psutil.virtual_memory()
        metrics["memory_percent"] = vm.percent
        metrics["memory_total_bytes"] = vm.total
        metrics["memory_used_bytes"] = vm.total - vm.available
        io1 = psutil.net_io_counters()
        time.sleep(0.1)
        io2 = psutil.net_io_counters()
        metrics["network_rx_bytes_per_sec"] = max(0, io2.bytes_recv - io1.bytes_recv) / 0.1
        metrics["network_tx_bytes_per_sec"] = max(0, io2.bytes_sent - io1.bytes_sent) / 0.1
        return metrics
    except Exception:
        metrics["notes"].append("psutil_not_available")

    if platform.system().lower() == "linux":
        metrics["cpu_percent"] = _get_linux_cpu_percent()
        used, total, percent = _get_linux_memory()
        metrics["memory_used_bytes"] = used
        metrics["memory_total_bytes"] = total
        metrics["memory_percent"] = percent
        rx_rate, tx_rate = _get_linux_network_rate()
        metrics["network_rx_bytes_per_sec"] = rx_rate
        metrics["network_tx_bytes_per_sec"] = tx_rate
    else:
        metrics["notes"].append("platform_metrics_unavailable")
    return metrics


def _get_process_metrics(
    sample_seconds: float | None = 0.1, process: Any | None = None
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "cpu_percent": None,
        "memory_percent": None,
        "memory_rss_bytes": None,
        "memory_vms_bytes": None,
        "notes": [],
    }
    try:
        import psutil  # type: ignore

        proc = process or psutil.Process(os.getpid())
        if sample_seconds is None:
            metrics["cpu_percent"] = proc.cpu_percent(interval=None)
        else:
            metrics["cpu_percent"] = proc.cpu_percent(interval=sample_seconds)
        mem = proc.memory_info()
        metrics["memory_percent"] = proc.memory_percent()
        metrics["memory_rss_bytes"] = mem.rss
        metrics["memory_vms_bytes"] = mem.vms
        return metrics
    except Exception:
        metrics["notes"].append("psutil_not_available")
    return metrics


def _get_disk_usage() -> list[dict[str, Any]]:
    try:
        import psutil  # type: ignore
    except Exception:
        return []

    disks: list[dict[str, Any]] = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        disks.append(
            {
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "percent": usage.percent,
            }
        )
    return disks


def _build_network_interfaces(
    now_counters: dict[str, Any],
    stats: dict[str, Any],
    prev_counters: dict[str, Any] | None,
    delta_seconds: float | None,
) -> list[dict[str, Any]]:
    interfaces: list[dict[str, Any]] = []
    for name, counters in now_counters.items():
        stat = stats.get(name)
        rx_rate = None
        tx_rate = None
        if prev_counters and delta_seconds and delta_seconds > 0:
            prev = prev_counters.get(name)
            if prev:
                rx_rate = max(0.0, (counters.bytes_recv - prev.bytes_recv) / delta_seconds)
                tx_rate = max(0.0, (counters.bytes_sent - prev.bytes_sent) / delta_seconds)
        interfaces.append(
            {
                "name": name,
                "is_up": bool(stat.isup) if stat else False,
                "speed_mbps": stat.speed if stat else None,
                "rx_bytes_per_sec": rx_rate,
                "tx_bytes_per_sec": tx_rate,
            }
        )
    return interfaces


def _get_network_interfaces(sample_seconds: float = 0.1) -> list[dict[str, Any]]:
    try:
        import psutil  # type: ignore
    except Exception:
        return []
    try:
        stats = psutil.net_if_stats()
        io1 = psutil.net_io_counters(pernic=True)
        time.sleep(sample_seconds)
        io2 = psutil.net_io_counters(pernic=True)
        return _build_network_interfaces(io2, stats, io1, sample_seconds)
    except Exception:
        return []


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """
    递归合并字典：用于构建“模板 + line 覆盖”的最终配置，
    以及按字段更新 server.json。
    """
    result = dict(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _check_database(session_factory):
    try:
        with session_factory() as session:
            session.execute(text("SELECT 1"))
        return True, None
    except Exception as exc:
        return False, str(exc)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    user: dict[str, Any]


class UIConfigPayload(BaseModel):
    themePreset: str
    customTheme: bool
    theme: str
    language: str
    fontSize: int
    compactMode: bool
    showGridLines: bool
    animationSpeed: int
    primaryColor: str
    accentColor: str
    autoRefreshInterval: int


class MockDataPayload(BaseModel):
    config: dict[str, Any]
    templates: list[dict[str, Any]]


class CacheTemplateUpdate(BaseModel):
    memory_cache: dict[str, Any] | None = None
    disk_cache: dict[str, Any] | None = None


class CacheLineUpdate(BaseModel):
    key: str = Field(..., description="?? key?map.json lines[].key?")
    memory_cache: dict[str, Any] | None = Field(
        default=None,
        description="?? configs/current/generated/{key}/{view}/server.json ? memory_cache ?????",
    )
    disk_cache: dict[str, Any] | None = Field(
        default=None,
        description="?? configs/current/generated/{key}/{view}/server.json ? disk_cache ?????",
    )


class CacheConfigUpdatePayload(BaseModel):
    """
    /config/cache 更新载荷：
    - templates: 修改 configs/current/server.json 中的 cache 字段。
    - lines:     按 key 修改对应产线视图的 cache 覆盖字段。
    """

    templates: CacheTemplateUpdate | None = None
    lines: list[CacheLineUpdate] | None = None


class TemplateConfigPayload(BaseModel):
    server: dict[str, Any] = Field(default_factory=dict)
    defect_class: dict[str, Any] = Field(default_factory=dict)


class TemplateConfigUpdatePayload(BaseModel):
    server: dict[str, Any] | None = None
    defect_class: dict[str, Any] | None = None


class LineViewOverridePayload(BaseModel):
    view: str
    database: dict[str, Any] | None = None
    images: dict[str, Any] | None = None
    memory_cache: dict[str, Any] | None = None
    disk_cache: dict[str, Any] | None = None


class LineSettingsPayload(BaseModel):
    views: list[LineViewOverridePayload] = Field(default_factory=list)
    defect_class_mode: str = Field(default="template")
    defect_class: dict[str, Any] | None = None


class UserCreatePayload(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    roles: list[str] = Field(default_factory=list)
    is_active: bool = True
    is_superuser: bool = False


class UserUpdatePayload(BaseModel):
    username: str | None = None
    password: str | None = None
    roles: list[str] | None = None
    is_active: bool | None = None
    is_superuser: bool | None = None


class RoleCreatePayload(BaseModel):
    name: str = Field(..., min_length=1)
    description: str | None = None


class RoleUpdatePayload(BaseModel):
    name: str | None = None
    description: str | None = None


class PolicyPayload(BaseModel):
    ptype: str = Field(..., min_length=1)
    v0: str | None = None
    v1: str | None = None
    v2: str | None = None
    v3: str | None = None
    v4: str | None = None
    v5: str | None = None


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, session: Session = Depends(deps.get_management_db)):
    user = rbac_manager.validate_login(session, payload.username, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    return {"user": user}


@router.get("/config/ui-settings")
def get_ui_settings(session: Session = Depends(deps.get_management_db)):
    return rbac_manager.get_config(session, "ui_settings", rbac_manager.DEFAULT_UI_CONFIG)


@router.put("/config/ui-settings")
def set_ui_settings(
    payload: UIConfigPayload,
    session: Session = Depends(deps.get_management_db),
):
    rbac_manager.set_config(session, "ui_settings", payload.model_dump())
    return {"status": "ok"}


@router.get("/config/mock-data")
def get_mock_data(session: Session = Depends(deps.get_management_db)):
    return rbac_manager.get_config(session, "mock_data", rbac_manager.DEFAULT_MOCKDATA_CONFIG)


@router.put("/config/mock-data")
def set_mock_data(
    payload: MockDataPayload,
    session: Session = Depends(deps.get_management_db),
):
    rbac_manager.set_config(session, "mock_data", payload.model_dump())
    return {"status": "ok"}


@router.get("/config/nginx")
def get_nginx_config():
    if not NGINX_CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail="nginx.conf not found")
    try:
        content = NGINX_CONFIG_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"path": str(NGINX_CONFIG_PATH), "content": content}


@router.get("/config/system-info")
def get_system_info():
    settings = deps.get_settings()
    config = load_map_config()
    lines = [str(item.get("name") or item.get("key") or "") for item in (config.get("lines") or [])]
    lines = [name for name in lines if name]

    main_ok, main_error = _check_database(deps.get_main_db_context)
    manage_ok, manage_error = _check_database(deps.get_management_db_context)

    db_settings = settings.database
    port_value = None if db_settings.drive == "sqlite" else db_settings.resolved_port
    response = {
        "line_names": lines,
        "database": {
            "drive": db_settings.drive,
            "host": db_settings.host,
            "port": port_value,
            "database_type": db_settings.database_type,
            "management_database": db_settings.management_database,
            "test_mode": settings.test_mode,
            "main_status": "ok" if main_ok else "error",
            "main_error": main_error,
            "management_status": "ok" if manage_ok else "error",
            "management_error": manage_error,
        },
        "server": {
            "hostname": socket.gethostname(),
            "os_name": platform.system(),
            "platform": platform.platform(),
            "platform_release": platform.release(),
            "platform_version": platform.version(),
            "cpu_count": os.cpu_count() or 0,
            "cpu_model": platform.processor() or platform.machine(),
        },
        "runtime": {
            "python_version": sys.version.split()[0],
            "python_executable": sys.executable,
        },
        "resources": _get_resource_metrics(),
        "service_resources": _get_process_metrics(),
        "disks": _get_disk_usage(),
        "network_interfaces": _get_network_interfaces(),
    }
    return response


@router.get("/system-info")
def get_system_info_alias():
    return get_system_info()


@router.get("/mate")
def get_config_mate():
    _ensure_current_dir()
    root = resolve_net_table_dir()
    map_path = root / "map.json"
    main_payload: dict[str, Any] = {}
    if VERSION_CONFIG_PATH.exists() and VERSION_CONFIG_PATH.stat().st_size > 0:
        try:
            version_payload = json.loads(VERSION_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(version_payload, dict):
                main_payload = {
                    "service_version": version_payload.get("version") or "0.0.0",
                }
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=500, detail=f"Invalid version.json: {exc}") from exc
    else:
        main_payload = {
            "service_version": "0.0.0",
        }
    if map_path.exists() and map_path.stat().st_size > 0:
        try:
            payload = json.loads(map_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=500, detail=f"Invalid map.json: {exc}") from exc
    else:
        _, fallback = load_map_payload()
        payload = {"views": fallback.get("views") or {}, "lines": fallback.get("lines") or []}
    if not isinstance(payload, dict):
        payload = {"views": {}, "lines": []}
    payload.setdefault("meta", {})
    if not isinstance(payload["meta"], dict):
        payload["meta"] = {}
    payload["meta"] = {**main_payload, **payload["meta"]}
    return {"path": str(map_path), "payload": payload}


def _split_cache_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    memory_cache = payload.get("memory_cache") or {}
    disk_cache = payload.get("disk_cache") or {}
    legacy_cache = payload.get("cache") or {}
    if not isinstance(memory_cache, dict):
        memory_cache = {}
    if not isinstance(disk_cache, dict):
        disk_cache = {}
    if isinstance(legacy_cache, dict):
        memory_keys = {
            "max_frames",
            "max_tiles",
            "max_mosaics",
            "max_defect_crops",
            "ttl_seconds",
        }
        disk_keys = {
            "defect_cache_enabled",
            "defect_cache_expand",
            "disk_cache_enabled",
            "disk_cache_max_records",
            "disk_cache_scan_interval_seconds",
            "disk_cache_cleanup_interval_seconds",
            "disk_precache_enabled",
            "disk_precache_levels",
            "disk_precache_workers",
        }
        for key in memory_keys:
            if key in legacy_cache and key not in memory_cache:
                memory_cache[key] = legacy_cache[key]
        for key in disk_keys:
            if key in legacy_cache and key not in disk_cache:
                disk_cache[key] = legacy_cache[key]
    return memory_cache, disk_cache


def _load_server_template() -> dict[str, Any]:
    """
    加载 configs/current/server.json 中的 database/images/cache 段。
    """
    _ensure_current_dir()
    if not CURRENT_SERVER_CONFIG_PATH.exists():
        return {"database": {}, "images": {}, "memory_cache": {}, "disk_cache": {}}
    try:
        payload = json.loads(CURRENT_SERVER_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"database": {}, "images": {}, "memory_cache": {}, "disk_cache": {}}
    memory_cache, disk_cache = _split_cache_payload(payload)
    return {
        "database": payload.get("database") or {},
        "images": payload.get("images") or {},
        "memory_cache": memory_cache,
        "disk_cache": disk_cache,
    }


def _save_server_template(updates: dict[str, Any]) -> None:
    """
    对 configs/current/server.json 的 database/images/cache 做增量更新。
    """
    if not updates:
        return
    _ensure_current_dir()
    if not CURRENT_SERVER_CONFIG_PATH.exists():
        return
    try:
        payload = json.loads(CURRENT_SERVER_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    for key in ("database", "images", "memory_cache", "disk_cache"):
        if key in updates and isinstance(updates.get(key), dict):
            current = payload.get(key) or {}
            if not isinstance(current, dict):
                current = {}
            payload[key] = _deep_merge(current, updates[key])
    try:
        CURRENT_SERVER_CONFIG_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        return


def _load_defect_class_template() -> dict[str, Any]:
    _ensure_current_dir()
    path = CURRENT_DIR / "DefectClass.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_defect_class_template(payload: dict[str, Any]) -> None:
    _ensure_current_dir()
    path = CURRENT_DIR / "DefectClass.json"
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return


def _ensure_line_view_override(line_key: str, view_key: str) -> Path:
    safe_key = line_key.replace("/", "_").replace("\\", "_")
    safe_view = view_key.replace("/", "_").replace("\\", "_")
    target_dir = CURRENT_DIR / "generated" / safe_key / safe_view
    target_dir.mkdir(parents=True, exist_ok=True)
    override_path = target_dir / "server.json"
    if not override_path.exists():
        override_path.write_text(
            json.dumps({"database": {}, "images": {}, "memory_cache": {}, "disk_cache": {}}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return override_path


def _load_line_view_override(line_key: str, view_key: str) -> dict[str, Any]:
    override_path = _ensure_line_view_override(line_key, view_key)
    try:
        payload = json.loads(override_path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    memory_cache, disk_cache = _split_cache_payload(payload)
    return {
        "database": payload.get("database") or {},
        "images": payload.get("images") or {},
        "memory_cache": memory_cache,
        "disk_cache": disk_cache,
    }


def _load_line_defect_class(line_key: str) -> tuple[str, dict[str, Any]]:
    safe_key = line_key.replace("/", "_").replace("\\", "_")
    custom_path = CURRENT_DIR / "generated" / safe_key / "DefectClass.json"
    if custom_path.exists():
        try:
            payload = json.loads(custom_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        return "custom", payload if isinstance(payload, dict) else {}
    return "template", _load_defect_class_template()


def _build_cache_config_payload() -> dict[str, Any]:
    """
    Build cache config payload with memory_cache and disk_cache.
    """
    _ensure_current_dir()
    root, map_payload = load_map_payload()
    lines = map_payload.get("lines") or []
    views = map_payload.get("views") or {}

    templates = _load_server_template()

    line_items: list[dict[str, Any]] = []
    for line in lines:
        name = str(line.get("name") or "")
        key = str(line.get("key") or name)
        profile = str(line.get("profile") or line.get("api_profile") or "default")
        mode = str(line.get("mode") or "direct")
        ip = line.get("ip")
        port = line.get("port") or line.get("listen_port")

        view_items: list[dict[str, Any]] = []
        view_keys = list(views.keys()) if isinstance(views, dict) and views else ["2D"]
        for view_key in view_keys:
            overrides = _load_line_view_override(key, view_key)
            effective_memory = _deep_merge(
                templates.get("memory_cache") or {},
                overrides.get("memory_cache") or {},
            )
            effective_disk = _deep_merge(
                templates.get("disk_cache") or {},
                overrides.get("disk_cache") or {},
            )
            view_items.append(
                {
                    "view": view_key,
                    "memory_cache": effective_memory,
                    "disk_cache": effective_disk,
                }
            )

        line_items.append(
            {
                "name": name,
                "key": key,
                "profile": profile,
                "mode": mode,
                "ip": ip,
                "port": port,
                "overrides": {},
                "views": view_items,
            }
        )

    return {
        "hostname": socket.gethostname(),
        "config_root": str(root),
        "config_root_name": root.name,
        "map_path": str(root / "map.json"),
        "server_path": str(CURRENT_SERVER_CONFIG_PATH),
        "templates": {
            "memory_cache": templates.get("memory_cache") or {},
            "disk_cache": templates.get("disk_cache") or {},
        },
        "views": views,
        "lines": line_items,
    }


@router.get("/cache")
def get_cache_config() -> dict[str, Any]:
    """
    读取缓存配置视图：
    - templates: configs/current/server.json 中的 cache 段。
    - lines:     各产线视图的 cache 覆盖与视图生效 cache。
    """
    return _build_cache_config_payload()


@router.put("/cache")
def update_cache_config(payload: CacheConfigUpdatePayload) -> dict[str, Any]:
    """
    Update cache config for memory_cache and disk_cache.
    """
    if payload.templates is not None:
        template_updates: dict[str, Any] = {}
        if payload.templates.memory_cache:
            template_updates["memory_cache"] = payload.templates.memory_cache
        if payload.templates.disk_cache:
            template_updates["disk_cache"] = payload.templates.disk_cache
        if template_updates:
            _save_server_template(template_updates)

    root, map_payload = load_map_payload()
    if payload.lines:
        views = map_payload.get("views") or {}
        view_keys = list(views.keys()) if isinstance(views, dict) and views else ["2D"]
        line_updates: dict[str, dict[str, Any]] = {}
        for item in payload.lines:
            if item.memory_cache or item.disk_cache:
                line_updates[item.key] = {
                    "memory_cache": item.memory_cache or {},
                    "disk_cache": item.disk_cache or {},
                }
        if line_updates:
            for line in map_payload.get("lines") or []:
                name = str(line.get("name") or "")
                key = str(line.get("key") or name)
                override = line_updates.get(key)
                if not override:
                    continue
                for view_key in view_keys:
                    override_path = CURRENT_DIR / "generated" / key / view_key / "server.json"
                    override_path.parent.mkdir(parents=True, exist_ok=True)
                    existing: dict[str, Any] = {
                        "database": {},
                        "images": {},
                        "memory_cache": {},
                        "disk_cache": {},
                    }
                    if override_path.exists():
                        try:
                            existing = json.loads(override_path.read_text(encoding="utf-8"))
                        except Exception:
                            existing = {
                                "database": {},
                                "images": {},
                                "memory_cache": {},
                                "disk_cache": {},
                            }
                    if not isinstance(existing, dict):
                        existing = {
                            "database": {},
                            "images": {},
                            "memory_cache": {},
                            "disk_cache": {},
                        }
                    current_memory, current_disk = _split_cache_payload(existing)
                    existing["memory_cache"] = _deep_merge(current_memory, override.get("memory_cache") or {})
                    existing["disk_cache"] = _deep_merge(current_disk, override.get("disk_cache") or {})
                    override_path.write_text(
                        json.dumps(existing, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

    return _build_cache_config_payload()


@router.get("/config/template")
def get_template_config() -> TemplateConfigPayload:
    _ensure_current_dir()
    server_payload = _load_server_template()
    defect_class_payload = _load_defect_class_template()
    return TemplateConfigPayload(server=server_payload, defect_class=defect_class_payload)


@router.put("/config/template")
def update_template_config(payload: TemplateConfigUpdatePayload) -> TemplateConfigPayload:
    if payload.server is not None:
        server_update: dict[str, Any] = {}
        for key in ("database", "images", "memory_cache", "disk_cache"):
            value = payload.server.get(key) if isinstance(payload.server, dict) else None
            if isinstance(value, dict):
                server_update[key] = value
        if server_update:
            _save_server_template(server_update)
    if payload.defect_class is not None and isinstance(payload.defect_class, dict):
        _save_defect_class_template(payload.defect_class)
    return get_template_config()


@router.get("/config/line-settings/{key}")
def get_line_settings(key: str) -> dict[str, Any]:
    _ensure_current_dir()
    root, map_payload = load_map_payload()
    views = map_payload.get("views") or {}
    view_keys = list(views.keys()) if isinstance(views, dict) and views else ["2D"]
    view_items = []
    for view_key in view_keys:
        overrides = _load_line_view_override(key, view_key)
        view_items.append(
            {
                "view": view_key,
                "database": overrides.get("database") or {},
                "images": overrides.get("images") or {},
                "memory_cache": overrides.get("memory_cache") or {},
                "disk_cache": overrides.get("disk_cache") or {},
            }
        )
    defect_mode, defect_payload = _load_line_defect_class(key)
    return {
        "key": key,
        "views": view_items,
        "defect_class_mode": defect_mode,
        "defect_class": defect_payload,
        "config_root": str(root),
    }


@router.put("/config/line-settings/{key}")
def update_line_settings(key: str, payload: LineSettingsPayload) -> dict[str, Any]:
    _ensure_current_dir()
    if payload.views:
        for item in payload.views:
            view_key = str(item.view or "").strip() or "2D"
            override_path = _ensure_line_view_override(key, view_key)
            existing: dict[str, Any] = {
                "database": {},
                "images": {},
                "memory_cache": {},
                "disk_cache": {},
            }
            if override_path.exists():
                try:
                    existing = json.loads(override_path.read_text(encoding="utf-8"))
                except Exception:
                    existing = {
                        "database": {},
                        "images": {},
                        "memory_cache": {},
                        "disk_cache": {},
                    }
            if not isinstance(existing, dict):
                existing = {
                    "database": {},
                    "images": {},
                    "memory_cache": {},
                    "disk_cache": {},
                }
            for section in ("database", "images", "memory_cache", "disk_cache"):
                value = getattr(item, section)
                if isinstance(value, dict):
                    existing[section] = value
                elif value is None:
                    existing.setdefault(section, {})
            override_path.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    mode = (payload.defect_class_mode or "template").lower()
    safe_key = key.replace("/", "_").replace("\\", "_")
    defect_path = CURRENT_DIR / "generated" / safe_key / "DefectClass.json"
    if mode == "custom":
        defect_path.parent.mkdir(parents=True, exist_ok=True)
        defect_payload = payload.defect_class if isinstance(payload.defect_class, dict) else {}
        defect_path.write_text(
            json.dumps(defect_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    else:
        if defect_path.exists():
            try:
                defect_path.unlink()
            except OSError:
                pass
    return get_line_settings(key)


@router.websocket("/ws/system-metrics")
async def ws_system_metrics(websocket: WebSocket):
    await websocket.accept()
    interval = 1.0
    prev_counters: dict[str, Any] | None = None
    prev_ts: float | None = None
    process = None
    try:
        import psutil  # type: ignore

        process = psutil.Process(os.getpid())
        process.cpu_percent(interval=None)
    except Exception:
        process = None
    try:
        while True:
            now_ts = time.time()
            if process is None:
                payload = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "resources": _get_resource_metrics(),
                    "service_resources": _get_process_metrics(sample_seconds=None),
                    "disks": _get_disk_usage(),
                    "network_interfaces": [],
                }
                await websocket.send_json(payload)
                await asyncio.sleep(interval)
                continue

            counters = psutil.net_io_counters(pernic=True)
            stats = psutil.net_if_stats()
            delta = now_ts - prev_ts if prev_ts is not None else None
            interfaces = _build_network_interfaces(counters, stats, prev_counters, delta)

            rx_rates = [item["rx_bytes_per_sec"] for item in interfaces if item["rx_bytes_per_sec"] is not None]
            tx_rates = [item["tx_bytes_per_sec"] for item in interfaces if item["tx_bytes_per_sec"] is not None]
            metrics = {
                "cpu_percent": psutil.cpu_percent(interval=None),
                "memory_percent": None,
                "memory_total_bytes": None,
                "memory_used_bytes": None,
                "network_rx_bytes_per_sec": sum(rx_rates) if rx_rates else None,
                "network_tx_bytes_per_sec": sum(tx_rates) if tx_rates else None,
                "notes": [],
            }
            vm = psutil.virtual_memory()
            metrics["memory_percent"] = vm.percent
            metrics["memory_total_bytes"] = vm.total
            metrics["memory_used_bytes"] = vm.total - vm.available

            payload = {
                "timestamp": datetime.utcnow().isoformat(),
                "resources": metrics,
                "service_resources": _get_process_metrics(sample_seconds=None, process=process),
                "disks": _get_disk_usage(),
                "network_interfaces": interfaces,
            }
            await websocket.send_json(payload)

            prev_counters = counters
            prev_ts = now_ts
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        return


@router.get("/admin/users")
def list_users(session: Session = Depends(deps.get_management_db)):
    return {"items": rbac_manager.list_users(session)}


@router.post("/admin/users")
def create_user(payload: UserCreatePayload, session: Session = Depends(deps.get_management_db)):
    try:
        item = rbac_manager.create_user(
            session,
            payload.username,
            payload.password,
            payload.roles,
            payload.is_active,
            payload.is_superuser,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item}


@router.put("/admin/users/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdatePayload,
    session: Session = Depends(deps.get_management_db),
):
    try:
        item = rbac_manager.update_user(
            session,
            user_id,
            payload.username,
            payload.password,
            payload.roles,
            payload.is_active,
            payload.is_superuser,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item}


@router.delete("/admin/users/{user_id}")
def delete_user(user_id: int, session: Session = Depends(deps.get_management_db)):
    rbac_manager.delete_user(session, user_id)
    return {"status": "ok"}


@router.get("/admin/roles")
def list_roles(session: Session = Depends(deps.get_management_db)):
    return {"items": rbac_manager.list_roles(session)}


@router.post("/admin/roles")
def create_role(payload: RoleCreatePayload, session: Session = Depends(deps.get_management_db)):
    try:
        item = rbac_manager.create_role(session, payload.name, payload.description)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item}


@router.put("/admin/roles/{role_id}")
def update_role(
    role_id: int,
    payload: RoleUpdatePayload,
    session: Session = Depends(deps.get_management_db),
):
    try:
        item = rbac_manager.update_role(session, role_id, payload.name, payload.description)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item}


@router.delete("/admin/roles/{role_id}")
def delete_role(role_id: int, session: Session = Depends(deps.get_management_db)):
    rbac_manager.delete_role(session, role_id)
    return {"status": "ok"}


@router.get("/admin/policies")
def list_policies(session: Session = Depends(deps.get_management_db)):
    return {"items": rbac_manager.list_policies(session)}


@router.post("/admin/policies")
def create_policy(payload: PolicyPayload, session: Session = Depends(deps.get_management_db)):
    item = rbac_manager.create_policy(session, payload.model_dump())
    return {"item": item}


@router.put("/admin/policies/{policy_id}")
def update_policy(
    policy_id: int,
    payload: PolicyPayload,
    session: Session = Depends(deps.get_management_db),
):
    try:
        item = rbac_manager.update_policy(session, policy_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item}


@router.delete("/admin/policies/{policy_id}")
def delete_policy(policy_id: int, session: Session = Depends(deps.get_management_db)):
    rbac_manager.delete_policy(session, policy_id)
    return {"status": "ok"}


@router.get("/download/info")
def get_download_info() -> dict[str, Any]:
    return _build_download_info()


@router.get("/download/files/{file_path:path}")
def download_file(file_path: str):
    root = DOWNLOADS_ROOT.resolve()
    candidate = (root / file_path).resolve()
    if candidate == root or root not in candidate.parents:
        raise HTTPException(status_code=404, detail="File not found")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(candidate)
