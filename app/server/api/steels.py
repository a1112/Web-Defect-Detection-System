from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.server.api.dependencies import get_steel_service
from app.server.api.utils import grade_to_level
from app.server.schemas import UiSteelItem, UiSteelListResponse
from app.server.services.steel_service import SteelService

router = APIRouter(prefix="/api")


@router.get("/steels", response_model=UiSteelListResponse)
def api_list_steels(
    limit: int = Query(20, ge=1, le=500),
    defect_only: bool = False,
    start_seq: Optional[int] = Query(default=None, description="Start seqNo (exclusive)"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    service: SteelService = Depends(get_steel_service),
):
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


@router.get("/steels/search", response_model=UiSteelListResponse)
def api_search_steels(
    limit: int = Query(20, ge=1, le=500),
    seq_no: Optional[int] = Query(default=None, description="流水号精确匹配"),
    steel_no: Optional[str] = Query(default=None, description="钢板号模糊匹配"),
    date_from: Optional[datetime] = Query(default=None, description="起始时间（含）"),
    date_to: Optional[datetime] = Query(default=None, description="结束时间（含）"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    service: SteelService = Depends(get_steel_service),
):
    desc = order != "asc"
    base = service.search(
        limit=limit,
        seq_no=seq_no,
        steel_no=steel_no,
        start=date_from,
        end=date_to,
        desc=desc,
    )
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
