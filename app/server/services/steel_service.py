from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from bkjc_database.property.DataBaseInterFace import DataBaseInterFace

from ..schemas import SteelListResponse, SteelRecord


def _coerce_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


class SteelService:
    def __init__(self, db: DataBaseInterFace):
        self.db = db

    def list_recent(
        self,
        limit: int,
        defect_only: bool,
        start_seq: Optional[int],
        desc: bool,
    ) -> SteelListResponse:
        raw = self.db.getSteelByNum(limit, defectOnly=defect_only, startID=start_seq, desc=desc)
        items = [self._to_model(pair) for pair in raw]
        return SteelListResponse(count=len(items), items=items)

    def by_seq(self, seq_no: int) -> SteelListResponse:
        raw = self.db.getSteelBySeqNo(seq_no)
        items = [self._to_model(pair) for pair in raw]
        return SteelListResponse(count=len(items), items=items)

    def by_id(self, steel_id: int) -> SteelListResponse:
        raw = self.db.getSteelById(steel_id)
        items = [self._to_model(pair) for pair in raw]
        return SteelListResponse(count=len(items), items=items)

    def by_steel_no(self, steel_no: str) -> SteelListResponse:
        raw = self.db.getSteelBySteelNo(steel_no)
        items = [self._to_model(pair) for pair in raw]
        return SteelListResponse(count=len(items), items=items)

    def by_date(self, start: datetime, end: datetime) -> SteelListResponse:
        raw = self.db.getSteelByDate(start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"))
        items = [self._to_model(pair) for pair in raw]
        return SteelListResponse(count=len(items), items=items)

    def _to_model(self, pair: Iterable) -> SteelRecord:
        steel_obj = None
        extra = None
        if isinstance(pair, (list, tuple)) and len(pair) >= 1:
            steel_obj = pair[0]
            if len(pair) > 1:
                extra = pair[1]
        else:
            steel_obj = pair
        if steel_obj is None:
            raise ValueError("Invalid steel record payload")
        detect_time = getattr(steel_obj, "detectTime", None)
        return SteelRecord(
            seq_no=_coerce_int(getattr(steel_obj, "seqNo", None)),
            steel_id=str(getattr(steel_obj, "steelID", "")),
            steel_type=getattr(steel_obj, "steelType", None),
            produced_length=_coerce_int(getattr(steel_obj, "steelLen", None)),
            produced_width=_coerce_int(getattr(steel_obj, "width", None)),
            produced_thickness=_coerce_int(getattr(steel_obj, "thick", None)),
            defect_count=_coerce_int(getattr(steel_obj, "defectNum", None)),
            top_defect_count=_coerce_int(getattr(steel_obj, "TopDefectNum", None)),
            bottom_defect_count=_coerce_int(getattr(steel_obj, "BottomDefectNum", None)),
            detect_time=detect_time,
            grade=_coerce_int(getattr(steel_obj, "grade", None)),
            warn=_coerce_int(getattr(steel_obj, "warn", None)),
            client=getattr(steel_obj, "client", None),
            hardness=_coerce_int(getattr(steel_obj, "hard", None)),
            ordered_length=_coerce_int(getattr(extra, "len", None)),
            ordered_width=_coerce_int(getattr(extra, "width", None)),
            ordered_thickness=_coerce_int(getattr(extra, "thick", None)),
        )
