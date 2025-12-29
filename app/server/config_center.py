from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel

from app.server.api import admin
from app.server.net_table import load_map_payload, save_map_payload


class ProcessManager:
    def get_api_list(self) -> list[dict[str, Any]]:  # pragma: no cover - interface
        raise NotImplementedError

    def restart_line(self, line: str) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def restart_all(self) -> int:  # pragma: no cover - interface
        raise NotImplementedError


class LineConfigPayload(BaseModel):
    lines: list[dict[str, Any]]
    defaults: dict[str, Any] | None = None


def create_app(manager: ProcessManager) -> FastAPI:
    app = FastAPI(title="Config Center", version="0.1.0")
    router = APIRouter(prefix="/config")

    @router.get("/api_list")
    def api_list() -> dict[str, Any]:
        return {"items": manager.get_api_list()}

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
            "lines": payload.lines,
        }
        map_path = save_map_payload(merged)
        return {"path": str(map_path), "lines": merged.get("lines") or []}

    app.include_router(router)
    app.include_router(admin.router, prefix="/config")
    return app
