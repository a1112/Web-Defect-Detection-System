from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from app.server import deps
from app.server.schemas import HealthStatus
from app.server.utils.speed_test import make_speed_test_response

API_VERSION = "0.1.0"

router = APIRouter()


@router.get("/health", response_model=HealthStatus)
def healthcheck():
    """健康检查接口，用于判断服务是否存活及数据库大致状态。"""
    db_connected = False
    latency_ms: float | None = None
    try:
        with deps.get_main_db_context() as session:
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


@router.get("/api/speed_test")
def api_speed_test(chunk_kb: int = 256, total_mb: int = 64) -> StreamingResponse:
    """下载带宽测速接口，用于按当前产线实例测试 /api 通道带宽。

    与配置中心的 /config/speed_test 行为保持一致，使用统一工具函数：
    - 通过 query 参数控制单块大小和总下载量。
    - StreamingResponse 持续推送字节块。
    """
    return make_speed_test_response(chunk_kb=chunk_kb, total_mb=total_mb)
