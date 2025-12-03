from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from ..db.models.ncdhotstripdefect import Camdefect1, Camdefect2
from ..schemas import (
    BoundingBox,
    DefectRecord,
    DefectResponse,
    DefectStats,
)


class DefectService:
    """
    SQLAlchemy 驱动的缺陷查询服务，直接连接 ncdhotstripdefect 数据库。
    Camdefect1 视为上表面（top），Camdefect2 视为下表面（bottom）。
    """

    def __init__(self, session_factory):
        """
        :param session_factory: callable returning sqlalchemy.orm.Session
        """
        self.session_factory = session_factory

    def defects_by_seq(self, seq_no: int, surface: Optional[str]) -> DefectResponse:
        with self.session_factory() as session:
            up_items = self._fetch_defects(session, Camdefect1, seq_no) if surface in (None, "top") else []
            down_items = self._fetch_defects(session, Camdefect2, seq_no) if surface in (None, "bottom") else []

            items: List[DefectRecord] = []
            stats: List[DefectStats] = []

            if up_items:
                stats.append(DefectStats(surface="top", camera_id=1, count=len(up_items)))
            if down_items:
                stats.append(DefectStats(surface="bottom", camera_id=2, count=len(down_items)))

            for defect in up_items:
                items.append(self._to_model(defect, camera_id=defect.camNo or 1, surface="top"))
            for defect in down_items:
                items.append(self._to_model(defect, camera_id=defect.camNo or 2, surface="bottom"))

            return DefectResponse(
                seq_no=seq_no,
                up_total=len(up_items),
                down_total=len(down_items),
                stats=stats,
                items=items,
            )

    def get_defect(self, camera_id: int, defect_id: int) -> Optional[DefectRecord]:
        with self.session_factory() as session:
            model = Camdefect1 if camera_id == 1 else Camdefect2
            result = session.query(model).filter(model.defectID == defect_id).first()
            if not result:
                return None
            surface = "top" if model is Camdefect1 else "bottom"
            return self._to_model(result, camera_id=camera_id, surface=surface)

    def find_defect_by_surface(self, surface: str, defect_id: int) -> Optional[DefectRecord]:
        surface = surface.lower()
        model = Camdefect1 if surface == "top" else Camdefect2
        camera_id = 1 if surface == "top" else 2
        with self.session_factory() as session:
            result = session.query(model).filter(model.defectID == defect_id).first()
            if not result:
                return None
            return self._to_model(result, camera_id=camera_id, surface=surface)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _fetch_defects(self, session: Session, model, seq_no: int):
        return session.query(model).filter(model.seqNo == seq_no).all()

    def _to_model(self, defect, camera_id: int, surface: str) -> DefectRecord:
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
            surface=surface,  # type: ignore[arg-type]
            image_index=getattr(defect, "imgIndex", None),
            class_id=getattr(defect, "defectClass", None),
            grade=getattr(defect, "grade", None),
            area=getattr(defect, "area", None),
            bbox_image=bbox_img,
            bbox_source=bbox_src,
            bbox_object=bbox_obj,
        )
