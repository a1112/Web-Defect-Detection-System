from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.server.api.dependencies import get_image_service
from app.server.services.image_service import ImageService

router = APIRouter(prefix="/api")


def _image_media_type(fmt: str) -> str:
    return f"image/{fmt.lower()}"


@router.get("/images/frame")
def api_frame_image(
    surface: str = Query(..., pattern="^(top|bottom)$"),
    seq_no: int = Query(...),
    image_index: int = Query(..., ge=0),
    width: Optional[int] = Query(default=None, ge=1, le=8192),
    height: Optional[int] = Query(default=None, ge=1, le=8192),
    view: Optional[str] = Query(default=None),
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
        return Response(content=payload, media_type=_image_media_type(fmt))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/images/defect/{defect_id}")
def api_defect_crop(
    defect_id: int,
    surface: str = Query(..., pattern="^(top|bottom)$"),
    expand: int = Query(default=0, ge=0, le=512),
    width: Optional[int] = Query(default=None, ge=1, le=4096),
    height: Optional[int] = Query(default=None, ge=1, le=4096),
    fmt: str = Query(default="JPEG"),
    service: ImageService = Depends(get_image_service),
):
    """按缺陷 ID 裁剪缺陷区域，并在响应头返回缺陷元数据。"""
    try:
        data, defect = service.crop_defect(
            surface=surface,
            defect_id=defect_id,
            expand=expand,
            width=width,
            height=height,
            fmt=fmt,
        )
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
    seq_no: int = Query(...),
    image_index: int = Query(...),
    x: int = Query(..., ge=0),
    y: int = Query(..., ge=0),
    w: int = Query(..., ge=1),
    h: int = Query(..., ge=1),
    expand: int = Query(default=0, ge=0, le=512),
    width: Optional[int] = Query(default=None, ge=1, le=4096),
    height: Optional[int] = Query(default=None, ge=1, le=4096),
    fmt: str = Query(default="JPEG"),
    service: ImageService = Depends(get_image_service),
):
    """按自定义坐标裁剪指定帧，支持扩展边界及输出尺寸。"""
    try:
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
        return Response(content=payload, media_type=_image_media_type(fmt))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/images/tile")
def api_tile_image(
    surface: str = Query(..., pattern="^(top|bottom)$"),
    seq_no: int = Query(...),
    view: Optional[str] = Query(default=None),
    level: int = Query(default=0, ge=0, le=2),
    tile_x: int = Query(..., ge=0),
    tile_y: int = Query(..., ge=0),
    tile_size: Optional[int] = Query(default=None, ge=64),
    orientation: str = Query(default="vertical", pattern="^(horizontal|vertical)$"),
    fmt: str = Query(default="JPEG"),
    service: ImageService = Depends(get_image_service),
):
    """按瓦片信息返回拼接图的分块，便于大图分片加载。"""
    try:
        payload = service.get_tile(
            surface=surface,
            seq_no=seq_no,
            view=view,
            level=level,
            tile_x=tile_x,
            tile_y=tile_y,
            tile_size=tile_size,
            orientation=orientation,
            fmt=fmt,
        )
        headers = {
            "X-Tile-Level": str(level),
            "X-Tile-X": str(tile_x),
            "X-Tile-Y": str(tile_y),
            "X-Tile-Size": str(service.settings.images.frame_height),
            "X-Tile-Orientation": orientation,
        }
        return Response(content=payload, media_type=_image_media_type(fmt), headers=headers)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
