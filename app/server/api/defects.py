from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.server.api.dependencies import get_defect_service, get_image_service
from app.server.api.utils import defect_class_label, grade_to_severity, get_defect_class_payload
from app.server.schemas import SurfaceImageInfo, UiDefectItem, UiDefectResponse
from app.server.services.defect_service import DefectService
from app.server.services.image_service import ImageService

router = APIRouter(prefix="/api")


@router.get("/ui/defects/{seq_no}", response_model=UiDefectResponse)
def api_ui_defects(
    seq_no: int,
    surface: Optional[str] = Query(default=None, pattern="^(top|bottom)$"),
    service: DefectService = Depends(get_defect_service),
    image_service: ImageService = Depends(get_image_service),
):
    """
    Web UI 专用缺陷列表接口。

    将内部 DefectRecord 映射为前端 Raw 类型所需字段。
    """
    base = service.defects_by_seq(seq_no, surface=surface)
    defects: list[UiDefectItem] = []
    for record in base.items:
        bbox = record.bbox_source or record.bbox_image
        width = max(0, bbox.right - bbox.left)
        height = max(0, bbox.bottom - bbox.top)
        defect_type = defect_class_label(record.class_id)
        severity = grade_to_severity(record.grade)
        defects.append(
            UiDefectItem(
                defect_id=str(record.defect_id),
                defect_type=defect_type,
                severity=severity,  # type: ignore[arg-type]
                x=bbox.left,
                y=bbox.top,
                width=width,
                height=height,
                confidence=1.0,
                surface=record.surface,  # type: ignore[arg-type]
                image_index=record.image_index or 0,
            )
        )

    surfaces = ["top", "bottom"] if surface is None else [surface]
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

    return UiDefectResponse(
        seq_no=base.seq_no,
        defects=defects,
        total_count=len(defects),
        surface_images=surface_images or None,
    )


@router.get("/defect-classes")
def api_defect_classes():
    """返回缺陷字典定义（读取 configs/DefectClass.json）。"""
    try:
        return get_defect_class_payload()
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="DefectClass.json not found")
