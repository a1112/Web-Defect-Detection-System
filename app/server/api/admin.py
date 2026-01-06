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

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
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
DEFAULT_SERVER_CONFIG_PATH = CONFIGS_DIR / "server.json"
SMALL_SERVER_CONFIG_PATH = CONFIGS_DIR / "server_small.json"


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


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """
    递归合并字典：用于构建“模板 + defaults + line 覆盖”的最终配置，
    以及按字段更新 server.json / map.json 中的 images 段。
    """
    result = dict(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result

    try:
        stats = psutil.net_if_stats()
        io1 = psutil.net_io_counters(pernic=True)
        time.sleep(sample_seconds)
        io2 = psutil.net_io_counters(pernic=True)
        return _build_network_interfaces(io2, stats, io1, sample_seconds)
    except Exception:
        return []


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
    default: dict[str, Any] | None = None
    small: dict[str, Any] | None = None


class CacheLineUpdate(BaseModel):
    key: str = Field(..., description="产线 key（map.json lines[].key）")
    images: dict[str, Any] | None = Field(
        default=None,
        description="写入 map.json 的 images 覆盖配置（部分字段更新）。",
    )


class CacheConfigUpdatePayload(BaseModel):
    """
    /config/cache 更新载荷：
    - templates: 修改全局模板（configs/server.json / server_small.json 中的 images 字段，按 profile 区分）。
    - defaults:  修改 map.json 中 defaults 段（通常继承到所有产线）。
    - lines:     按 key 修改对应产线的 images 覆盖字段。
    """

    templates: CacheTemplateUpdate | None = None
    defaults: dict[str, Any] | None = None
    lines: list[CacheLineUpdate] | None = None


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

    main_ok, main_error = _check_database(deps.get_main_db)
    manage_ok, manage_error = _check_database(deps.get_management_db)

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
        "disks": _get_disk_usage(),
        "network_interfaces": _get_network_interfaces(),
    }
    return response


@router.get("/system-info")
def get_system_info_alias():
    return get_system_info()


@router.get("/mate")
def get_config_mate():
    root = resolve_net_table_dir()
    map_path = root / "map.json"
    if map_path.exists() and map_path.stat().st_size > 0:
        try:
            payload = json.loads(map_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=500, detail=f"Invalid map.json: {exc}") from exc
    else:
        _, fallback = load_map_payload()
        payload = {"defaults": fallback.get("defaults") or {}, "lines": fallback.get("lines") or []}
    return {"path": str(map_path), "payload": payload}


def _load_template_images() -> dict[str, dict[str, Any]]:
    """
    加载全局模板 server.json / server_small.json 中的 images 段。

    返回结构：{"default": {...}, "small": {...}}
    """
    templates: dict[str, dict[str, Any]] = {"default": {}, "small": {}}

    for profile, path in (("default", DEFAULT_SERVER_CONFIG_PATH), ("small", SMALL_SERVER_CONFIG_PATH)):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            images = payload.get("images") or {}
            if isinstance(images, dict):
                templates[profile] = images
        except Exception:
            continue
    return templates


def _save_template_images(profile: str, updates: dict[str, Any]) -> None:
    """
    按 profile（default/small）对 server.json / server_small.json 的 images 段做增量更新。
    """
    if not updates:
        return
    if profile == "small":
        path = SMALL_SERVER_CONFIG_PATH
    else:
        path = DEFAULT_SERVER_CONFIG_PATH
    if not path.exists():
        # 不强制创建新文件，避免误操作；后续如有需要可扩展。
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    images = payload.get("images") or {}
    if not isinstance(images, dict):
        images = {}
    merged = _deep_merge(images, updates)
    payload["images"] = merged
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return


def _build_cache_config_payload() -> dict[str, Any]:
    """
    汇总缓存相关配置：
    - 当前 hostname 所在的 net_table 目录（例如 configs/net_tabel/DATA/DESKTOP-xxx）。
    - map.json 中 defaults 与 lines。
    - server.json / server_small.json 中 images 段，作为模板。
    - 计算每条产线实际生效的 images（模板 + defaults + line 覆盖）。
    """
    root, map_payload = load_map_payload()
    defaults = map_payload.get("defaults") or {}
    defaults_images = defaults.get("images") or {}
    lines = map_payload.get("lines") or []

    templates = _load_template_images()

    line_items: list[dict[str, Any]] = []
    for line in lines:
        name = str(line.get("name") or "")
        key = str(line.get("key") or name)
        profile = str(line.get("profile") or line.get("api_profile") or "default")
        mode = str(line.get("mode") or "direct")
        ip = line.get("ip")
        port = line.get("port") or line.get("listen_port")

        line_images = line.get("images") or line.get("image") or {}
        if not isinstance(line_images, dict):
            line_images = {}

        base_images = templates.get("small" if profile == "small" else "default") or {}
        effective_images = _deep_merge(base_images, defaults_images)
        effective_images = _deep_merge(effective_images, line_images)

        line_items.append(
            {
                "name": name,
                "key": key,
                "profile": profile,
                "mode": mode,
                "ip": ip,
                "port": port,
                "overrides": {"images": line_images},
                "effective": {"images": effective_images},
            }
        )

    return {
        "hostname": socket.gethostname(),
        "map_root": str(root),
        "map_root_name": root.name,
        "templates": templates,
        "defaults": {"images": defaults_images},
        "lines": line_items,
    }


@router.get("/cache")
def get_cache_config() -> dict[str, Any]:
    """
    读取缓存配置视图：
    - templates: server.json / server_small.json 中的 images 段。
    - defaults:  map.json defaults.images。
    - lines:     各产线的 images 覆盖与实际生效 images。
    """
    return _build_cache_config_payload()


@router.put("/cache")
def update_cache_config(payload: CacheConfigUpdatePayload) -> dict[str, Any]:
    """
    更新缓存配置：
    - templates: 写回到 server.json / server_small.json 的 images 段。
    - defaults:  写回 map.json.defaults（深度合并）。
    - lines:     按 key 写回 map.json.lines[].images（深度合并）。
    """
    # 1. 更新全局模板
    if payload.templates is not None:
        if payload.templates.default:
            _save_template_images("default", payload.templates.default)
        if payload.templates.small:
            _save_template_images("small", payload.templates.small)

    # 2. 更新 map.json 默认与产线覆盖
    root, map_payload = load_map_payload()
    defaults = map_payload.get("defaults") or {}
    if payload.defaults:
        defaults = _deep_merge(defaults, payload.defaults)
        map_payload["defaults"] = defaults

    if payload.lines:
        line_updates: dict[str, dict[str, Any]] = {}
        for item in payload.lines:
            if item.images:
                line_updates[item.key] = item.images
        if line_updates:
            lines = map_payload.get("lines") or []
            for line in lines:
                name = str(line.get("name") or "")
                key = str(line.get("key") or name)
                override = line_updates.get(key)
                if not override:
                    continue
                line_images = line.get("images") or line.get("image") or {}
                if not isinstance(line_images, dict):
                    line_images = {}
                merged = _deep_merge(line_images, override)
                line["images"] = merged
            map_payload["lines"] = lines

    # 写回 map.json
    save_map_payload(map_payload)

    # 返回最新视图
    return _build_cache_config_payload()


@router.websocket("/ws/system-metrics")
async def ws_system_metrics(websocket: WebSocket):
    await websocket.accept()
    interval = 1.0
    prev_counters: dict[str, Any] | None = None
    prev_ts: float | None = None
    try:
        while True:
            now_ts = time.time()
            try:
                import psutil  # type: ignore
            except Exception:
                payload = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "resources": _get_resource_metrics(),
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
