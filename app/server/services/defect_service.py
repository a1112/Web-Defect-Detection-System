from __future__ import annotations

from typing import List, Optional

from bkjc_database.property.DataBaseInterFace import DataBaseInterFace

from ..schemas import (
    BoundingBox,
    DefectRecord,
    DefectResponse,
    DefectStats,
)


class DefectService:
    def __init__(self, db: DataBaseInterFace):
        self.db = db
        camera_list = db.getCameraList() or [[1], [2]]
        self.up_cameras = camera_list[0] if camera_list else [1]
        self.down_cameras = camera_list[1] if len(camera_list) > 1 else [2]

    def defects_by_seq(self, seq_no: int, surface: Optional[str]) -> DefectResponse:
        payload = self.db.getDefectBySeqNo(seq_no)
        up_total = int(payload.get("upCount", 0) or 0)
        down_total = int(payload.get("downCount", 0) or 0)
        items: List[DefectRecord] = []
        stats: List[DefectStats] = []
        for camera_id, defect_info in payload.items():
            if not isinstance(camera_id, int):
                continue
            is_up = bool(defect_info.get("is_up"))
            surface_name = "top" if is_up else "bottom"
            if surface and surface != surface_name:
                continue
            defects = defect_info.get("defect") or []
            stats.append(
                DefectStats(surface=surface_name, camera_id=camera_id, count=len(defects)),
            )
            for defect in defects:
                items.append(self._to_model(defect, camera_id=camera_id, is_up=is_up))
        return DefectResponse(seq_no=seq_no, up_total=up_total, down_total=down_total, stats=stats, items=items)

    def get_defect(self, camera_id: int, defect_id: int) -> Optional[DefectRecord]:
        result = self.db.getDefectItem(camera_id, defect_id)
        if not result:
            return None
        is_up = camera_id in self.up_cameras
        return self._to_model(result, camera_id=camera_id, is_up=is_up)

    def find_defect_by_surface(self, surface: str, defect_id: int) -> Optional[DefectRecord]:
        surface = surface.lower()
        camera_ids = self.up_cameras if surface == "top" else self.down_cameras
        for camera_id in camera_ids:
            record = self.get_defect(camera_id, defect_id)
            if record:
                return record
        return None

    def _to_model(self, defect, camera_id: int, is_up: bool) -> DefectRecord:
        bbox_img = BoundingBox(
            left=int(getattr(defect, "leftInImg", 0) or 0),
            top=int(getattr(defect, "topInImg", 0) or 0),
            right=int(getattr(defect, "rightInImg", 0) or 0),
            bottom=int(getattr(defect, "bottomInImg", 0) or 0),
        )
        bbox_src = BoundingBox(
            left=int(getattr(defect, "leftInSrcImg", getattr(defect, "leftInImg", 0)) or 0),
            top=int(getattr(defect, "topInSrcImg", getattr(defect, "topInImg", 0)) or 0),
            right=int(getattr(defect, "rightInSrcImg", getattr(defect, "rightInImg", 0)) or 0),
            bottom=int(getattr(defect, "bottomInSrcImg", getattr(defect, "bottomInImg", 0)) or 0),
        )
        bbox_obj = BoundingBox(
            left=int(getattr(defect, "leftInObj", getattr(defect, "leftInImg", 0)) or 0),
            top=int(getattr(defect, "topInObj", getattr(defect, "topInImg", 0)) or 0),
            right=int(getattr(defect, "rightInObj", getattr(defect, "rightInImg", 0)) or 0),
            bottom=int(getattr(defect, "bottomInObj", getattr(defect, "bottomInImg", 0)) or 0),
        )
        return DefectRecord(
            defect_id=int(getattr(defect, "defectID", getattr(defect, "id", 0)) or 0),
            seq_no=int(getattr(defect, "seqNo", 0) or 0),
            camera_id=camera_id,
            surface="top" if is_up else "bottom",
            image_index=getattr(defect, "imgIndex", None),
            class_id=getattr(defect, "defectClass", None),
            grade=getattr(defect, "grade", None),
            area=getattr(defect, "area", None),
            bbox_image=bbox_img,
            bbox_source=bbox_src,
            bbox_object=bbox_obj,
        )
