from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class SteelRecord(BaseModel):
    seq_no: int
    steel_id: str
    steel_type: Optional[str] = None
    ordered_length: Optional[int] = Field(default=None, description="Length from order")
    ordered_width: Optional[int] = None
    ordered_thickness: Optional[int] = None
    produced_length: Optional[int] = None
    produced_width: Optional[int] = None
    produced_thickness: Optional[int] = None
    defect_count: Optional[int] = None
    top_defect_count: Optional[int] = None
    bottom_defect_count: Optional[int] = None
    detect_time: Optional[datetime] = None
    grade: Optional[int] = None
    warn: Optional[int] = None
    client: Optional[str] = None
    hardness: Optional[int] = None


class SteelListResponse(BaseModel):
    count: int
    items: list[SteelRecord]


class BoundingBox(BaseModel):
    left: int
    top: int
    right: int
    bottom: int


class DefectRecord(BaseModel):
    defect_id: int
    seq_no: int
    camera_id: int
    surface: Literal["top", "bottom"]
    image_index: Optional[int]
    class_id: Optional[int]
    grade: Optional[int]
    area: Optional[int]
    bbox_image: Optional[BoundingBox]
    bbox_source: Optional[BoundingBox]
    bbox_object: Optional[BoundingBox]


class DefectStats(BaseModel):
    surface: Literal["top", "bottom"]
    camera_id: int
    count: int


class DefectResponse(BaseModel):
    seq_no: int
    up_total: int
    down_total: int
    stats: list[DefectStats]
    items: list[DefectRecord]


class ImageDescriptor(BaseModel):
    surface: Literal["top", "bottom"]
    seq_no: int
    image_index: int
    view: str = Field(default="2D")
    format: str = Field(default="jpeg")


class TileDescriptor(BaseModel):
    surface: Literal["top", "bottom"]
    seq_no: int
    view: str
    level: int
    tile_x: int
    tile_y: int
    tile_size: int

