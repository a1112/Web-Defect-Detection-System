from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.server.api.dependencies import get_steel_service
from app.server.api.utils import grade_to_level
from app.server.schemas import (
    SteelListResponse,
    UiSteelItem,
    UiSteelListResponse,
)
from app.server.services.steel_service import SteelService

router = APIRouter(prefix="/api")


@router.get("/steels", response_model=SteelListResponse)
def api_list_steels(
    limit: int = Query(20, ge=1, le=500),
    defect_only: bool = False,
    start_seq: Optional[int] = Query(default=None, description="Start seqNo (exclusive)"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    service: SteelService = Depends(get_steel_service),
):
    """按序号倒序查询最近的钢卷列表，支持缺陷过滤和升降序切换。"""
    desc = order != "asc"
    return service.list_recent(limit=limit, defect_only=defect_only, start_seq=start_seq, desc=desc)


@router.get("/steels/date", response_model=SteelListResponse)
def api_list_steels_by_date(
    start: datetime = Query(..., description="Start datetime (inclusive)"),
    end: datetime = Query(..., description="End datetime (inclusive)"),
    service: SteelService = Depends(get_steel_service),
):
    """按时间范围查询钢卷列表（闭区间）。"""
    return service.by_date(start=start, end=end)


@router.get("/steels/steel-no/{steel_no}", response_model=SteelListResponse)
def api_steel_by_no(steel_no: str, service: SteelService = Depends(get_steel_service)):
    """根据钢卷号精确查询钢卷信息。"""
    return service.by_steel_no(steel_no)


@router.get("/steels/id/{steel_id}", response_model=SteelListResponse)
def api_steel_by_id(steel_id: int, service: SteelService = Depends(get_steel_service)):
    """根据数据库 ID 查询钢卷信息。"""
    return service.by_id(steel_id)


@router.get("/steels/seq/{seq_no}", response_model=SteelListResponse)
def api_steel_by_seq(seq_no: int, service: SteelService = Depends(get_steel_service)):
    """根据序列号查询单卷记录。"""
    return service.by_seq(seq_no)


@router.get("/ui/steels", response_model=UiSteelListResponse)
def api_ui_list_steels(
    limit: int = Query(20, ge=1, le=500),
    defect_only: bool = False,
    start_seq: Optional[int] = Query(default=None, description="Start seqNo (exclusive)"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    service: SteelService = Depends(get_steel_service),
):
    """
    Web UI 专用钢板列表接口。

    返回字段命名与前端 Raw 类型一致，便于直接映射到可视化界面。
    """
    desc = order != "asc"
    base = service.list_recent(limit=limit, defect_only=defect_only, start_seq=start_seq, desc=desc)
    steels: list[UiSteelItem] = []
    for record in base.items:
        length = record.produced_length or record.ordered_length
        width = record.produced_width or record.ordered_width
        thickness = record.produced_thickness or record.ordered_thickness
        steels.append(
            UiSteelItem(
                seq_no=record.seq_no,
                steel_no=record.steel_id,
                steel_type=record.steel_type,
                length=length,
                width=width,
                thickness=thickness,
                timestamp=record.detect_time,
                level=grade_to_level(record.grade),
                defect_count=record.defect_count,
            )
        )
    return UiSteelListResponse(steels=steels, total=len(steels))

