from __future__ import annotations

from typing import Any
import os

from fastapi import APIRouter

from app.server.status_service import get_status_service

router = APIRouter(prefix="/api")


@router.get("/status")
def api_status() -> dict[str, Any]:
    service = get_status_service()
    return {
        "line": {
            "key": os.getenv("DEFECT_LINE_KEY") or os.getenv("DEFECT_LINE_NAME"),
            "name": os.getenv("DEFECT_LINE_NAME"),
            "kind": os.getenv("DEFECT_LINE_KIND") or "default",
            "host": os.getenv("DEFECT_LINE_HOST"),
            "port": os.getenv("DEFECT_LINE_PORT"),
        },
        "services": service.list_services(),
    }


@router.get("/status/simple")
def api_status_simple() -> dict[str, Any]:
    service = get_status_service()
    return service.get_simple_status()


@router.get("/status/{service_name}/log")
def api_status_log(service_name: str, cursor: int = 0, limit: int = 200) -> dict[str, Any]:
    service = get_status_service()
    return service.get_logs(service_name, cursor=cursor, limit=limit)


@router.post("/status/{service_name}/log/clear")
def api_status_log_clear(service_name: str) -> dict[str, Any]:
    service = get_status_service()
    service.clear_logs(service_name)
    return {"ok": True}
