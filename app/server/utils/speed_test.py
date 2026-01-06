from __future__ import annotations

from typing import Optional

from fastapi.responses import StreamingResponse


def make_speed_test_response(chunk_kb: int = 256, total_mb: int = 64) -> StreamingResponse:
    """构造带宽测速的 StreamingResponse。

    参数会被裁剪到合理范围，以防过大的内存占用：
    - chunk_kb: [32, 4096]
    - total_mb: [1, 4096]；当 total_mb <= 0 时表示无限流，由客户端控制时长。
    """
    size_kb = max(32, min(4096, int(chunk_kb)))

    try:
        total_mb_int = int(total_mb)
    except (TypeError, ValueError):
        total_mb_int = 0

    total_bytes: Optional[int]
    if total_mb_int <= 0:
        # total_mb <= 0 视为无限流，由客户端中断连接控制测试时间
        total_bytes = None
    else:
        total_mb_int = max(1, min(4096, total_mb_int))
        total_bytes = total_mb_int * 1024 * 1024

    chunk = bytes(size_kb * 1024)
    mv = memoryview(chunk)

    def iter_chunks():
        if total_bytes is None:
            while True:
                yield mv
        else:
            remaining = total_bytes
            while remaining > 0:
                size = min(remaining, len(mv))
                yield mv[:size]
                remaining -= size

    response = StreamingResponse(iter_chunks(), media_type="application/octet-stream")
    response.headers["Cache-Control"] = "no-store"
    if total_bytes is not None:
        response.headers["Content-Length"] = str(total_bytes)
    return response
