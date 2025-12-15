from __future__ import annotations

import math
from fastapi import APIRouter, HTTPException, Depends

from app.server.api.utils import get_defect_class_payload
from app.server.config.settings import ServerSettings
from app.server.api.dependencies import get_image_service
from app.server.schemas import SurfaceImageInfo
from app.server.services.image_service import ImageService

router = APIRouter(prefix="/api")


@router.get("/meta")
def api_meta():
    """
    Web UI 全局元信息。

    - defect_classes: 缺陷字典（原 /api/defect-classes 返回值）
    - tile: 瓦片相关全局配置，由服务端统一给出
    """
    try:
        defect_classes = get_defect_class_payload()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="DefectClass.json not found") from exc

    settings = ServerSettings.load()
    images = settings.images

    # 瓦片层级与尺寸从配置文件中读取
    ratio = images.frame_width / images.frame_height if images.frame_height else 1
    max_level = int(math.ceil(math.log(ratio, 2))) if ratio > 1 else 0

    tile_meta = {
        "max_level": max_level,
        "min_level": 0,
        "default_tile_size": images.frame_height,
    }

    image_meta = {
        "frame_width": images.frame_width,
        "frame_height": images.frame_height,
    }

    return {
        "defect_classes": defect_classes,
        "tile": tile_meta,
        "image": image_meta,
    }


@router.get("/steel-meta/{seq_no}")
def api_steel_meta(
    seq_no: int,
    image_service: ImageService = Depends(get_image_service),
):
    """
    返回指定钢板在当前实例下的图像元数据，指导前端渲染（分布图、瓦片加载等）。
    """
    surfaces = ["top", "bottom"]
    surface_images: list[SurfaceImageInfo] = []
    for surf in surfaces:
        try:
            frame_count, image_width, image_height = image_service.get_surface_image_info(
                surface=surf, seq_no=seq_no
            )
        except FileNotFoundError:
            continue
        surface_images.append(
            SurfaceImageInfo(
                surface=surf,  # type: ignore[arg-type]
                frame_count=frame_count,
                image_width=image_width,
                image_height=image_height,
            )
        )

    return {
        "seq_no": seq_no,
        "surface_images": surface_images,
    }
