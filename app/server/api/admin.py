from __future__ import annotations

from typing import Any
from pathlib import Path
import os
import platform
import socket
import sys
import time

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.server import deps
from app.server.rbac import manager as rbac_manager
from app.server.net_table import load_map_config

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
    }
    return response


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
