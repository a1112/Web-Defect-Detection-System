from __future__ import annotations

import math
from fastapi import APIRouter, HTTPException, Depends

from app.server.api.utils import get_defect_class_payload
from app.server import deps
from app.server.api.dependencies import get_image_service
from app.server.schemas import SurfaceImageInfo
from app.server.services.image_service import ImageService

router = APIRouter(prefix="/api")


def _calc_max_tile_level(image_width: int, tile_size: int) -> int:
    if tile_size <= 0 or image_width <= tile_size:
        return 0
    ratio = image_width / tile_size
    return max(0, int(math.floor(math.log(ratio, 2))))


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

    settings = deps.get_settings()
    images = settings.images
    disk_cache = settings.disk_cache

    # 瓦片层级与尺寸从配置文件中读取
    max_level = _calc_max_tile_level(images.frame_width, images.frame_height)

    tile_meta = {
        "max_level": max_level,
        "min_level": 0,
        "default_tile_size": images.frame_height,
        "tile_size": images.frame_height,
    }

    image_meta = {
        "frame_width": images.frame_width,
        "frame_height": images.frame_height,
        "org_width": getattr(images, "org_width", None),
        "org_height": getattr(images, "org_height", None),
    }

    return {
        "defect_classes": defect_classes,
        "tile": tile_meta,
        "image": image_meta,
        "defect_cache_expand": disk_cache.defect_cache_expand,
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
        tile_size = image_service.settings.images.frame_height
        max_level = 0
        if tile_size > 0 and image_width > tile_size:
            max_level = _calc_max_tile_level(image_width, tile_size)
        surface_images.append(
            SurfaceImageInfo(
                surface=surf,  # type: ignore[arg-type]
                frame_count=frame_count,
                image_width=image_width,
                image_height=image_height,
                max_level=max_level,
            )
        )

    return {
        "seq_no": seq_no,
        "surface_images": surface_images,
    }
