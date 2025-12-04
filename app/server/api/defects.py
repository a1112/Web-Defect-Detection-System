from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.server.api.dependencies import get_defect_service
from app.server.api.utils import defect_class_label, grade_to_severity, get_defect_class_payload
from app.server.schemas import DefectResponse, UiDefectItem, UiDefectResponse
from app.server.services.defect_service import DefectService

router = APIRouter(prefix="/api")


@router.get("/defects/{seq_no}", response_model=DefectResponse)
def api_defects(
    seq_no: int,
    surface: Optional[str] = Query(default=None, pattern="^(top|bottom)$"),
    service: DefectService = Depends(get_defect_service),
):
    """查询指定序列的缺陷列表，可按上下表面过滤。"""
    return service.defects_by_seq(seq_no, surface=surface)


@router.get("/ui/defects/{seq_no}", response_model=UiDefectResponse)
def api_ui_defects(
    seq_no: int,
    surface: Optional[str] = Query(default=None, pattern="^(top|bottom)$"),
    service: DefectService = Depends(get_defect_service),
):
    """
    Web UI 专用缺陷列表接口。

    将内部 DefectRecord 映射为前端 Raw 类型所需字段。
    """
    base = service.defects_by_seq(seq_no, surface=surface)
    defects: list[UiDefectItem] = []
    for record in base.items:
        bbox = record.bbox_image
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
    return UiDefectResponse(seq_no=base.seq_no, defects=defects, total_count=len(defects))


@router.get("/defect-classes")
def api_defect_classes():
    """返回缺陷字典定义（读取 configs/DefectClass.json）。"""
    try:
        return get_defect_class_payload()
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="DefectClass.json not found")
