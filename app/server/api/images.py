from __future__ import annotations

import logging
from typing import Optional, List
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response

from app.server.api.dependencies import get_image_service
from app.server.services.image_service import ImageService
from app.server.utils.image_ops import encode_image, open_image_from_bytes, resize_image

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


class TileInfo(BaseModel):
    level: int = Field(..., ge=0, le=16)
    tile_x: int = Field(..., ge=0)
    tile_y: int = Field(..., ge=0)
    tile_size: Optional[int] = Field(default=None, ge=1, le=16384)


class TilePreheatRequest(BaseModel):
    surface: str = Field(..., pattern="^(top|bottom)$")
    seq_no: int = Field(..., ge=0)
    tiles: List[TileInfo] = Field(...)
    view: Optional[str] = Field(default=None)
    priority: Optional[str] = Field(default="normal", pattern="^(low|normal|high)$")


class TilePreheatResponse(BaseModel):
    success: bool
    preheated: int
    message: str
    details: Optional[dict] = None


def _image_media_type(fmt: str) -> str:
    return f"image/{fmt.lower()}"

def _apply_scale(payload: bytes, scale: float, fmt: str, service: ImageService) -> bytes:
    if not payload or scale is None or scale <= 0:
        return payload
    if abs(scale - 1.0) < 1e-3:
        return payload
    try:
        image = open_image_from_bytes(payload, mode=service.mode)
    except Exception:
        logger.exception("Failed to decode image for scale=%s", scale)
        return payload
    target_w = max(1, int(round(image.width * scale)))
    target_h = max(1, int(round(image.height * scale)))
    if target_w == image.width and target_h == image.height:
        return payload
    resized = resize_image(image, width=target_w, height=target_h)
    return encode_image(resized, fmt=fmt)


@router.get("/images/frame")
def api_frame_image(
    surface: str = Query(..., pattern="^(top|bottom)$"),
    seq_no: int = Query(...),
    image_index: int = Query(..., ge=0),
    width: Optional[int] = Query(default=None, ge=1, le=8192),
    height: Optional[int] = Query(default=None, ge=1, le=8192),
    view: Optional[str] = Query(default=None),
    scale: float = Query(default=1.0, gt=0.0, le=1.0),
    fmt: str = Query(default="JPEG"),
    service: ImageService = Depends(get_image_service),
):
    """获取单帧图像，支持指定上下表面、视角与目标尺寸。"""
    try:
        payload = service.get_frame(
            surface=surface,
            seq_no=seq_no,
            image_index=image_index,
            view=view,
            width=width,
            height=height,
            fmt=fmt,
        )
        payload = _apply_scale(payload, scale, fmt, service)
        return Response(content=payload, media_type=_image_media_type(fmt))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/images/defect/{defect_id}")
def api_defect_crop(
    defect_id: int,
    surface: str = Query(..., pattern="^(top|bottom)$"),
    # 若不传 expand，后端将使用配置中的 defect_cache_expand 作为默认扩展像素
    expand: Optional[int] = Query(default=None, ge=0, le=512),
    width: Optional[int] = Query(default=None, ge=1, le=4096),
    height: Optional[int] = Query(default=None, ge=1, le=4096),
    force_crop: bool = Query(default=False),
    scale: float = Query(default=1.0, gt=0.0, le=1.0),
    fmt: str = Query(default="JPEG"),
    service: ImageService = Depends(get_image_service),
):
    """按缺陷 ID 裁剪缺陷区域，并在响应头返回缺陷元数据。"""
    try:
        logger.info(
            "defect crop request id=%s surface=%s expand=%s width=%s height=%s fmt=%s",
            defect_id,
            surface,
            expand,
            width,
            height,
            fmt,
        )
        data, defect = service.crop_defect(
            surface=surface,
            defect_id=defect_id,
            expand=expand,
            width=width,
            height=height,
            fmt=fmt,
            use_cache=not force_crop,
        )
        data = _apply_scale(data, scale, fmt, service)
        headers = {
            "X-Seq-No": str(defect.seq_no),
            "X-Image-Index": str(defect.image_index or 0),
            "X-Camera-Id": str(defect.camera_id),
        }
        return Response(content=data, media_type=_image_media_type(fmt), headers=headers)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/images/crop")
def api_custom_crop(
    surface: str = Query(..., pattern="^(top|bottom)$"),
    defect_id: Optional[int] = Query(default=None, ge=1),
    seq_no: Optional[int] = Query(default=None),
    image_index: Optional[int] = Query(default=None),
    x: Optional[int] = Query(default=None, ge=0),
    y: Optional[int] = Query(default=None, ge=0),
    w: Optional[int] = Query(default=None, ge=1),
    h: Optional[int] = Query(default=None, ge=1),
    expand: int = Query(default=0, ge=0, le=512),
    width: Optional[int] = Query(default=None, ge=1, le=4096),
    height: Optional[int] = Query(default=None, ge=1, le=4096),
    force_crop: bool = Query(default=False),
    scale: float = Query(default=1.0, gt=0.0, le=1.0),
    fmt: str = Query(default="JPEG"),
    service: ImageService = Depends(get_image_service),
):
    """按自定义坐标裁剪指定帧，支持扩展边界及输出尺寸。"""
    try:
        if defect_id is not None:
            payload, defect = service.crop_defect(
                surface=surface,
                defect_id=defect_id,
                expand=expand,
                width=width,
                height=height,
                fmt=fmt,
                use_cache=not force_crop,
            )
            payload = _apply_scale(payload, scale, fmt, service)
            headers = {
                "X-Seq-No": str(defect.seq_no),
                "X-Image-Index": str(defect.image_index or 0),
                "X-Camera-Id": str(defect.camera_id),
                "X-Defect-Id": str(defect.defect_id),
            }
            return Response(content=payload, media_type=_image_media_type(fmt), headers=headers)

        if seq_no is None or image_index is None or x is None or y is None or w is None or h is None:
            raise HTTPException(status_code=400, detail="Missing crop parameters")

        payload = service.crop_custom(
            surface=surface,
            seq_no=seq_no,
            image_index=image_index,
            x=x,
            y=y,
            w=w,
            h=h,
            expand=expand,
            width=width,
            height=height,
            fmt=fmt,
        )
        payload = _apply_scale(payload, scale, fmt, service)
        return Response(content=payload, media_type=_image_media_type(fmt))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/images/mosaic")
def api_mosaic_image(
    surface: str = Query(..., pattern="^(top|bottom)$"),
    seq_no: int = Query(...),
    view: Optional[str] = Query(default=None),
    limit: Optional[int] = Query(default=None, ge=1, le=10000),
    skip: int = Query(default=0, ge=0),
    stride: int = Query(default=1, ge=1),
    width: Optional[int] = Query(default=None, ge=1),
    height: Optional[int] = Query(default=None, ge=1),
    scale: float = Query(default=1.0, gt=0.0, le=1.0),
    fmt: str = Query(default="JPEG"),
    service: ImageService = Depends(get_image_service),
):
    """生成指定序列的长带拼接图，可配置抽帧、跳过数量和尺寸。"""
    try:
        payload = service.get_mosaic(
            surface=surface,
            seq_no=seq_no,
            view=view,
            limit=limit,
            skip=skip,
            stride=stride,
            width=width,
            height=height,
            fmt=fmt,
        )
        payload = _apply_scale(payload, scale, fmt, service)
        return Response(content=payload, media_type=_image_media_type(fmt))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/images/tile")
def api_tile_image(
    request: Request,
    surface: str = Query(..., pattern="^(top|bottom)$"),
    seq_no: int = Query(...),
    view: Optional[str] = Query(default=None),
    level: int = Query(default=0, ge=0, le=16),
    tile_x: int = Query(..., ge=0),
    tile_y: int = Query(..., ge=0),
    width: Optional[int] = Query(default=None, ge=1, le=16384),
    height: Optional[int] = Query(default=None, ge=1, le=16384),
    orientation: str = Query(default="vertical", pattern="^(horizontal|vertical)$"),
    prefetch: Optional[str] = Query(default=None),
    prefetch_x: Optional[float] = Query(default=None),
    prefetch_y: Optional[float] = Query(default=None),
    prefetch_image_index: Optional[int] = Query(default=None, ge=0),
    scale: float = Query(default=1.0, gt=0.0, le=1.0),
    fmt: str = Query(default="JPEG"),
    viewer_id: Optional[str] = Header(default=None, alias="X-Viewer-Id"),
    service: ImageService = Depends(get_image_service),
):
    """按瓦片信息返回拼接图的分块，便于大图分片加载。"""
    try:
        if view is not None and view.lower() == "horizontal":
            orientation = "horizontal"
            view = None
        resolved_viewer_id = viewer_id
        if not resolved_viewer_id:
            forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
            if forwarded:
                resolved_viewer_id = forwarded
            elif request.client:
                resolved_viewer_id = request.client.host
        payload = service.get_tile(
            surface=surface,
            seq_no=seq_no,
            view=view,
            level=level,
            tile_x=tile_x,
            tile_y=tile_y,
            orientation=orientation,
            width=width,
            height=height,
            fmt=fmt,
            viewer_id=resolved_viewer_id,
            prefetch=(
                {
                    "mode": prefetch,
                    "x": prefetch_x,
                    "y": prefetch_y,
                    "image_index": prefetch_image_index,
                }
                if prefetch
                else None
            ),
        )
        payload = _apply_scale(payload, scale, fmt, service)
        headers = {
            "X-Tile-Level": str(level),
            "X-Tile-X": str(tile_x),
            "X-Tile-Y": str(tile_y),
            "X-Tile-Size": str(service.settings.images.frame_height),
            "X-Tile-Orientation": orientation,
        }
        cache_ttl = int(getattr(service.settings.memory_cache, "ttl_seconds", 120) or 120)
        headers["Cache-Control"] = f"public, max-age={cache_ttl}"
        return Response(content=payload, media_type=_image_media_type(fmt), headers=headers)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/images/tile/preheat", response_model=TilePreheatResponse)
async def api_tile_preheat(
    request: TilePreheatRequest,
    http_request: Request,
    viewer_id: Optional[str] = Header(default=None, alias="X-Viewer-Id"),
    service: ImageService = Depends(get_image_service),
):
    """
    预热瓦片到缓存但不返回图像数据
    
    这个API允许前端智能预热瓦片，提高缓存命中率：
    1. 不返回图像数据，仅预热到后端缓存
    2. 支持批量预热多个瓦片
    3. 支持优先级调度
    4. 避免重复预热已缓存的瓦片
    """
    try:
        resolved_viewer_id = viewer_id
        if not resolved_viewer_id:
            forwarded = (http_request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
            if forwarded:
                resolved_viewer_id = forwarded
            elif http_request.client:
                resolved_viewer_id = http_request.client.host

        preheated_count = 0
        failed_count = 0
        already_cached_count = 0
        
        # 处理每个瓦片
        for tile_info in request.tiles:
            try:
                # 检查是否已缓存
                cache_key = f"{request.surface}-{request.seq_no}-{tile_info.level}-{tile_info.tile_x}-{tile_info.tile_y}-{tile_info.tile_size or service.settings.images.frame_height}-{request.view or 'default'}"
                
                if service.tile_cache.get(cache_key) is not None:
                    already_cached_count += 1
                    continue
                
                # 预热瓦片到缓存（不返回数据）
                service.get_tile(
                    surface=request.surface,
                    seq_no=request.seq_no,
                    view=request.view,
                    level=tile_info.level,
                    tile_x=tile_info.tile_x,
                    tile_y=tile_info.tile_y,
                    fmt="JPEG",
                    viewer_id=resolved_viewer_id,
                    prefetch=None,  # 不实际返回数据，仅预热到缓存
                )
                
                preheated_count += 1
                
            except Exception as e:
                logger.warning(f"Failed to preheat tile {tile_info.level}-{tile_info.tile_x}-{tile_info.tile_y}: {e}")
                failed_count += 1
                continue
        
        total_tiles = len(request.tiles)
        message = f"Processed {total_tiles} tiles: {preheated_count} preheated"
        if already_cached_count > 0:
            message += f", {already_cached_count} already cached"
        if failed_count > 0:
            message += f", {failed_count} failed"
        
        logger.info(f"Tile preheat: {message} (surface={request.surface}, seq_no={request.seq_no}, viewer={resolved_viewer_id})")
        
        return TilePreheatResponse(
            success=True,
            preheated=preheated_count,
            message=message,
            details={
                "total_requested": total_tiles,
                "already_cached": already_cached_count,
                "failed": failed_count,
                "viewer_id": resolved_viewer_id,
            }
        )
        
    except Exception as exc:
        logger.exception("Tile preheat API error")
        raise HTTPException(status_code=500, detail=f"Preheat failed: {str(exc)}") from exc
