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


class UiSteelItem(BaseModel):
    """Web UI 专用的钢板信息模型，字段命名与前端 Raw 类型一致。"""

    seq_no: int
    steel_no: str
    steel_type: Optional[str] = None
    length: Optional[int] = None
    width: Optional[int] = None
    thickness: Optional[int] = None
    timestamp: Optional[datetime] = None
    level: Literal["A", "B", "C", "D"] = "D"
    defect_count: Optional[int] = None


class UiSteelListResponse(BaseModel):
    steels: list[UiSteelItem]
    total: int


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


class UiDefectItem(BaseModel):
    """Web UI 专用的缺陷信息模型，字段命名与前端 Raw 类型一致。"""

    defect_id: str
    defect_type: str
    severity: Literal["low", "medium", "high"]
    x: int
    y: int
    width: int
    height: int
    confidence: float
    surface: Literal["top", "bottom"]
    image_index: int


class UiDefectResponse(BaseModel):
    seq_no: int
    defects: list[UiDefectItem]
    total_count: int
    surface_images: Optional[list[SurfaceImageInfo]] = None


class ImageDescriptor(BaseModel):
    surface: Literal["top", "bottom"]
    seq_no: int
    image_index: int
    view: str = Field(default="2D")
    format: str = Field(default="jpeg")


class SurfaceImageInfo(BaseModel):
    """按表面划分的帧图像元数据，用于前端绘制缺陷分布图。"""

    surface: Literal["top", "bottom"]
    frame_count: int = Field(description="该表面可用帧图像数量")
    image_width: int = Field(description="单帧图像宽度（像素）")
    image_height: int = Field(description="单帧图像高度（像素）")
    max_level: int = Field(description="此序列在当前瓦片规则下支持的最大瓦片级别")


class TileDescriptor(BaseModel):
    surface: Literal["top", "bottom"]
    seq_no: int
    view: str
    level: int
    tile_x: int
    tile_y: int
    tile_size: int


class DatabaseStatus(BaseModel):
    connected: bool
    latency_ms: Optional[float] = None


class HealthStatus(BaseModel):
    status: Literal["healthy", "unhealthy"]
    timestamp: datetime
    version: Optional[str] = None
    database: Optional[DatabaseStatus] = None
