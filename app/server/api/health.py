from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import text

from app.server import deps
from app.server.schemas import HealthStatus

API_VERSION = "0.1.0"

router = APIRouter()


@router.get("/health", response_model=HealthStatus)
def healthcheck():
    """健康检查接口，用于判断服务是否存活及数据库大致状态。"""
    db_connected = False
    latency_ms: float | None = None
    try:
        with deps.get_main_db() as session:
            session.execute(text("SELECT 1"))
            db_connected = True
    except Exception:  # pragma: no cover - 健康检查中容错
        db_connected = False

    status = "healthy" if db_connected else "unhealthy"
    return HealthStatus(
        status=status,
        timestamp=datetime.utcnow(),
        version=API_VERSION,
        database={
            "connected": db_connected,
            "latency_ms": latency_ms,
        },
    )


@router.get("/api/health", response_model=HealthStatus)
def healthcheck_api():
    return healthcheck()
