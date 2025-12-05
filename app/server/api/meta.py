from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.server.api.utils import get_defect_class_payload

router = APIRouter(prefix="/api")


@router.get("/ui/meta")
def api_ui_meta():
    """
    Web UI 全局元信息。

    - defect_classes: 缺陷字典（原 /api/defect-classes 返回值）
    - tile: 瓦片相关全局配置，由服务端统一给出
    """
    try:
        defect_classes = get_defect_class_payload()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="DefectClass.json not found") from exc

    # 目前瓦片层级固定为 0,1,2；瓦片尺寸默认 1024，与 /api/images/tile 保持一致
    tile_meta = {
        "max_level": 2,
        "min_level": 0,
        "default_tile_size": 1024,
    }

    return {
        "defect_classes": defect_classes,
        "tile": tile_meta,
    }

