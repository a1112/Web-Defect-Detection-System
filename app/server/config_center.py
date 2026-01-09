from __future__ import annotations

import logging
import os
import json
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from app.server.api import admin
from app.server.test_model import router as test_model_router
from app.server.net_table import load_map_payload, save_map_payload, resolve_net_table_dir
from app.server.utils.speed_test import make_speed_test_response
from app.server.status_service import get_status_service

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[2]
UI_BUILD_ENV_KEY = "DEFECT_UI_BUILD_DIR"
DEFAULT_UI_BUILD_DIR = (
    REPO_ROOT
    / "app"
    / "ui"
    / "DefectWebUi"
    / "build"
    / "WebAssembly_Qt_6_10_0_multi_threaded-MinSizeRel"
)
UI_BUILD_DIR = Path(os.getenv(UI_BUILD_ENV_KEY, DEFAULT_UI_BUILD_DIR))


class CoopCoepMiddleware(BaseHTTPMiddleware):
    """Ensure /ui responses can use SharedArrayBuffer by enabling cross-origin isolation."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path or ""
        if path == "/" or path.startswith("/ui"):
            response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
            response.headers.setdefault("Cross-Origin-Embedder-Policy", "require-corp")
            response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        return response


def _resolve_ui_index(ui_dir: Path) -> Path | None:
    for name in ("DefectWebUi.html", "index.html"):
        candidate = ui_dir / name
        if candidate.exists():
            return candidate
    return None


def _mount_ui(app: FastAPI) -> None:
    app.add_middleware(CoopCoepMiddleware)
    if UI_BUILD_DIR.exists():
        app.mount(
            "/ui",
            StaticFiles(directory=str(UI_BUILD_DIR), html=True),
            name="defect-web-ui",
        )

        @app.get("/", include_in_schema=False)
        async def serve_ui_root():
            index_path = _resolve_ui_index(UI_BUILD_DIR)
            if not index_path:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "Defect Web UI index not found inside "
                        f"{UI_BUILD_DIR}. Check your WASM build output."
                    ),
                )
            return FileResponse(index_path)
    else:
        logger.warning(
            "Defect Web UI build directory %s not found. "
            "Set %s to point at your Qt WASM output to enable the frontend.",
            UI_BUILD_DIR,
            UI_BUILD_ENV_KEY,
        )


class ProcessManager:
    def get_api_list(self) -> list[dict[str, Any]]:  # pragma: no cover - interface
        raise NotImplementedError

    def update_api_status(self, status: dict[str, Any]) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def restart_line(self, line: str) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def restart_all(self) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    def get_status_items(self, line_key: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_simple_status(self, line_key: str | None = None, kind: str | None = None) -> dict[str, Any] | None:
        raise NotImplementedError

    def get_service_logs(
        self,
        *,
        line_key: str,
        kind: str,
        service: str,
        cursor: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def clear_service_logs(self, *, line_key: str, kind: str, service: str) -> None:
        raise NotImplementedError


class LineConfigPayload(BaseModel):
    lines: list[dict[str, Any]]


class ApiStatusPayload(BaseModel):
    key: str
    name: str | None = None
    kind: str | None = None
    host: str | None = None
    port: int | None = None
    pid: int | None = None
    online: bool | None = None
    latest_timestamp: datetime | None = None
    latest_age_seconds: int | None = None
    services: list[dict[str, Any]] | None = None
    logs: list[dict[str, Any]] | None = None
    service_versions: dict[str, int] | None = None
    service_log_cursor: dict[str, int] | None = None


class SystemMonitor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._metrics: dict[str, Any] = {
            "cpu_percent": None,
            "memory": None,
            "disks": [],
            "updated_at": None,
            "disk_updated_at": None,
        }
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        last_disk = 0.0
        while not self._stop.is_set():
            now = time.time()
            metrics: dict[str, Any] = {}
            try:
                import psutil  # type: ignore

                metrics["cpu_percent"] = psutil.cpu_percent(interval=None)
                vm = psutil.virtual_memory()
                metrics["memory"] = {
                    "total": vm.total,
                    "used": vm.used,
                    "percent": vm.percent,
                }
                if now - last_disk >= 120:
                    disks = []
                    for part in psutil.disk_partitions(all=False):
                        try:
                            usage = psutil.disk_usage(part.mountpoint)
                        except Exception:
                            continue
                        disks.append(
                            {
                                "mountpoint": part.mountpoint,
                                "total": usage.total,
                                "used": usage.used,
                                "percent": usage.percent,
                            }
                        )
                    metrics["disks"] = disks
                    metrics["disk_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    last_disk = now
            except Exception:
                metrics["notes"] = ["psutil_not_available"]
            metrics["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self._lock:
                if metrics.get("cpu_percent") is not None:
                    self._metrics["cpu_percent"] = metrics.get("cpu_percent")
                if metrics.get("memory") is not None:
                    self._metrics["memory"] = metrics.get("memory")
                if metrics.get("disks") is not None:
                    self._metrics["disks"] = metrics.get("disks", [])
                if metrics.get("disk_updated_at"):
                    self._metrics["disk_updated_at"] = metrics.get("disk_updated_at")
                self._metrics["updated_at"] = metrics.get("updated_at")
            self._stop.wait(5)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._metrics)


def create_app(manager: ProcessManager) -> FastAPI:
    app = FastAPI(title="Config Center", version="0.1.0")
    _mount_ui(app)
    monitor = SystemMonitor()
    router = APIRouter(prefix="/config")

    @router.get("/api_list")
    def api_list() -> dict[str, Any]:
        return {"items": manager.get_api_list()}

    @router.post("/api_status")
    def api_status(payload: ApiStatusPayload) -> dict[str, Any]:
        manager.update_api_status(payload.dict())
        return {"status": "ok"}

    @router.get("/speed_test")
    def speed_test(chunk_kb: int = 256, total_mb: int = 64) -> StreamingResponse:
        return make_speed_test_response(chunk_kb=chunk_kb, total_mb=total_mb)

    @router.post("/restart")
    def restart_all() -> dict[str, Any]:
        restarted = manager.restart_all()
        return {"restarted": restarted}

    @router.post("/restart/{line}")
    def restart_line(line: str) -> dict[str, Any]:
        ok = manager.restart_line(line)
        if not ok:
            raise HTTPException(status_code=404, detail=f"Line '{line}' not found")
        return {"restarted": line}

    @router.get("/lines")
    def get_lines() -> dict[str, Any]:
        root, payload = load_map_payload()
        return {
            "root": str(root),
            "views": payload.get("views") or {},
            "lines": payload.get("lines") or [],
        }

    @router.get("/status")
    def config_status(line_key: str | None = None, kind: str | None = None) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        try:
            items = manager.get_status_items(line_key=line_key, kind=kind)
        except Exception:
            logger.exception("Failed to build status items.")
        control_item = None
        try:
            status_service = get_status_service()
            control_services = [
                item for item in status_service.list_services() if item.get("name") == "image_generate"
            ]
            control_item = {
                "key": "__control__",
                "name": "控制中心",
                "kind": "center",
                "host": "config_center",
                "port": None,
                "services": control_services,
            }
        except Exception:
            logger.exception("Failed to build control center status.")
        if control_item:
            items = [control_item, *items]
        return {"items": items, "system_monitor": monitor.snapshot()}

    @router.get("/status/simple")
    def config_status_simple(line_key: str | None = None, kind: str | None = None) -> dict[str, Any]:
        item = None
        try:
            status_service = get_status_service()
            control_services = [
                item for item in status_service.list_services() if item.get("name") == "image_generate"
            ]
            control_simple = None
            if control_services:
                control_simple = {
                    "state": control_services[0].get("state"),
                    "message": control_services[0].get("message"),
                    "service": control_services[0].get("name"),
                    "label": control_services[0].get("label"),
                    "priority": control_services[0].get("priority"),
                    "data": control_services[0].get("data") or {},
                    "updated_at": control_services[0].get("updated_at"),
                }
            api_simple = manager.get_simple_status(line_key=line_key, kind=kind)
            if control_simple and str(control_simple.get("state") or "").lower() == "error":
                item = control_simple
                item["key"] = "__control__"
            elif api_simple and str(api_simple.get("state") or "").lower() == "error":
                item = api_simple
            elif control_simple and str(control_simple.get("state") or "").lower() == "running":
                item = control_simple
                item["key"] = "__control__"
            else:
                item = api_simple or control_simple
        except Exception:
            logger.exception("Failed to build simple status.")
        return {"item": item, "system_monitor": monitor.snapshot()}

    @router.get("/status/{line_key}/{kind}/log")
    def config_status_log(
        line_key: str,
        kind: str,
        service: str | None = None,
        cursor: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        name = service or "all"
        if line_key == "__control__":
            status_service = get_status_service()
            return status_service.get_logs(name, cursor=cursor, limit=limit)
        return manager.get_service_logs(line_key=line_key, kind=kind, service=name, cursor=cursor, limit=limit)

    @router.post("/status/{line_key}/{kind}/log/clear")
    def config_status_log_clear(line_key: str, kind: str, service: str | None = None) -> dict[str, Any]:
        name = service or "all"
        if line_key == "__control__":
            status_service = get_status_service()
            status_service.clear_logs(name)
        else:
            manager.clear_service_logs(line_key=line_key, kind=kind, service=name)
        return {"ok": True}

    @router.put("/lines")
    def save_lines(payload: LineConfigPayload) -> dict[str, Any]:
        current_root, current_payload = load_map_payload()
        current_views = current_payload.get("views") or {}
        current_lines = current_payload.get("lines") or []
        merged = {
            "views": current_payload.get("views") or {},
            "lines": payload.lines,
        }
        map_path = save_map_payload(merged)
        generated_root = resolve_net_table_dir() / "generated"
        generated_root.mkdir(parents=True, exist_ok=True)
        old_by_name = {
            str(item.get("name") or ""): str(item.get("key") or item.get("name") or "")
            for item in current_lines
            if isinstance(item, dict)
        }
        for line in payload.lines:
            if not isinstance(line, dict):
                continue
            name = str(line.get("name") or "")
            key = str(line.get("key") or name)
            if not key:
                continue
            prev_key = old_by_name.get(name)
            if prev_key and prev_key != key:
                old_path = generated_root / prev_key
                new_path = generated_root / key
                if old_path.exists() and not new_path.exists():
                    old_path.rename(new_path)
            view_keys = list(current_views.keys()) if isinstance(current_views, dict) and current_views else ["2D"]
            for view in view_keys:
                target_dir = generated_root / key / view
                target_dir.mkdir(parents=True, exist_ok=True)
                override_path = target_dir / "server.json"
                if not override_path.exists():
                    override_path.write_text(
                        json.dumps(
                            {"database": {}, "images": {}, "cache": {}},
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
        return {"path": str(map_path), "lines": merged.get("lines") or []}

    app.include_router(router)
    app.include_router(admin.router, prefix="/config")
    app.include_router(test_model_router)
    return app
