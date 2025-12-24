from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException


class ProcessManager:
    def get_api_list(self) -> list[dict[str, Any]]:  # pragma: no cover - interface
        raise NotImplementedError

    def restart_line(self, line: str) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def restart_all(self) -> int:  # pragma: no cover - interface
        raise NotImplementedError


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

    app.include_router(router)
    return app
