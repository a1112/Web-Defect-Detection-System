from __future__ import annotations

import logging
import os
from pathlib import Path
from datetime import datetime
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from app.server.api import admin
from app.server.net_table import load_map_payload, save_map_payload
from app.server.utils.speed_test import make_speed_test_response

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


class LineConfigPayload(BaseModel):
    lines: list[dict[str, Any]]
    defaults: dict[str, Any] | None = None


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


def create_app(manager: ProcessManager) -> FastAPI:
    app = FastAPI(title="Config Center", version="0.1.0")
    _mount_ui(app)
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
        return {"root": str(root), "defaults": payload.get("defaults") or {}, "lines": payload.get("lines") or []}

    @router.put("/lines")
    def save_lines(payload: LineConfigPayload) -> dict[str, Any]:
        current_root, current_payload = load_map_payload()
        merged = {
            "defaults": payload.defaults if payload.defaults is not None else current_payload.get("defaults") or {},
            "views": current_payload.get("views") or {},
            "lines": payload.lines,
        }
        map_path = save_map_payload(merged)
        return {"path": str(map_path), "lines": merged.get("lines") or []}

    app.include_router(router)
    app.include_router(admin.router, prefix="/config")
    return app
