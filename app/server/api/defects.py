from __future__ import annotations

from typing import Optional
import threading

from fastapi import APIRouter, Depends, HTTPException, Query

from app.server.api.dependencies import get_defect_service, get_image_service
from app.server.api.utils import defect_class_label, grade_to_severity, get_defect_class_payload
from app.server.schemas import SurfaceImageInfo, UiDefectItem, UiDefectResponse
from app.server.services.defect_service import DefectService
from app.server.services.image_service import ImageService

router = APIRouter(prefix="/api")


@router.get("/defects/{seq_no}", response_model=UiDefectResponse)
def api_defects(
    seq_no: int,
    surface: Optional[str] = Query(default=None, pattern="^(top|bottom)$"),
    service: DefectService = Depends(get_defect_service),
    image_service: ImageService = Depends(get_image_service),
):
    base = service.defects_by_seq(seq_no, surface=surface)
    defects: list[UiDefectItem] = []

    # SMALL 实例：如果配置了像素缩放（例如 0.5），则需要对 bbox_source/bbox_image 做对应缩放，
    # 使返回的坐标与当前实例提供的图像尺寸保持一致。
    try:
        scale = float(getattr(image_service.settings.images, "pixel_scale", 1.0))
    except Exception:
        scale = 1.0
    if scale <= 0:
        scale = 1.0

    for record in base.items:
        bbox = record.bbox_source or record.bbox_image
        bbox_obj = record.bbox_object

        if scale != 1.0 and bbox is not None:
            left = int(round(bbox.left * scale))
            top = int(round(bbox.top * scale))
            right = int(round(bbox.right * scale))
            bottom = int(round(bbox.bottom * scale))
        elif bbox is not None:
            left = bbox.left
            top = bbox.top
            right = bbox.right
            bottom = bbox.bottom
        else:
            left = top = right = bottom = 0

        width = max(0, right - left)
        height = max(0, bottom - top)

        # 物理坐标（mm），来自 bbox_object，对应 leftInObj/...，只用于前端展示，不参与裁剪。
        if bbox_obj is not None:
            left_mm = bbox_obj.left
            top_mm = bbox_obj.top
            right_mm = bbox_obj.right
            bottom_mm = bbox_obj.bottom
            width_mm = max(0, right_mm - left_mm)
            height_mm = max(0, bottom_mm - top_mm)
        else:
            left_mm = top_mm = width_mm = height_mm = None
        defect_type = defect_class_label(record.class_id)
        severity = grade_to_severity(record.grade)
        defects.append(
            UiDefectItem(
                defect_id=str(record.defect_id),
                defect_type=defect_type,
                severity=severity,  # type: ignore[arg-type]
                x=left,
                y=top,
                width=width,
                height=height,
                confidence=1.0,
                surface=record.surface,  # type: ignore[arg-type]
                image_index=record.image_index or 0,
                x_mm=left_mm,
                y_mm=top_mm,
                width_mm=width_mm,
                height_mm=height_mm,
            )
        )

    return UiDefectResponse(
        seq_no=base.seq_no,
        defects=defects,
        total_count=len(defects),
        surface_images=None,
    )

    # NOTE: 传统模式缺陷分析界面通常会在获取缺陷列表后立即请求各缺陷小图。
    # 这里在后台线程中预热该板所有缺陷小图，尽量保证前端随后请求
    # /api/images/defect/{defect_id} 时直接命中磁盘缓存，而不是在线裁剪。
    if getattr(image_service.settings.cache, "disk_cache_enabled", False) and getattr(
        image_service.settings.cache, "defect_cache_enabled", True
    ):
        threading.Thread(
            target=image_service.warmup_defects_for_seq,
            args=(seq_no, surface),
            daemon=True,
        ).start()


@router.get("/defect-classes")
def api_defect_classes():
    """返回缺陷字典定义（读取 configs/DefectClass.json）。"""
    try:
        return get_defect_class_payload()
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="DefectClass.json not found")
