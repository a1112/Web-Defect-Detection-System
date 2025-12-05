from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db.models.ncdplate import Rcvsteelprop, Steelrecord
from ..schemas import SteelListResponse, SteelRecord


def _coerce_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


class SteelService:
    """
    SQLAlchemy 驱动的钢板查询服务，直接连接 ncdhotstrip 数据库。
    """

    def __init__(self, session_factory):
        """
        :param session_factory: callable returning sqlalchemy.orm.Session
        """
        self.session_factory = session_factory

    def list_recent(
        self,
        limit: int,
        defect_only: bool,
        start_seq: Optional[int],
        desc: bool,
    ) -> SteelListResponse:
        with self.session_factory() as session:
            order_field = Steelrecord.seqNo.desc() if desc else Steelrecord.seqNo.asc()
            query = session.query(Steelrecord)
            if start_seq is not None:
                query = query.filter(Steelrecord.seqNo > start_seq) if desc else query.filter(
                    Steelrecord.seqNo < start_seq
                )
            if defect_only:
                query = query.filter(Steelrecord.defectNum.isnot(None)).filter(Steelrecord.defectNum > 0)

            records = query.order_by(order_field).limit(limit).all()

            items = self._map_records(session, records, limit)
            return SteelListResponse(count=len(items), items=items)

    def by_seq(self, seq_no: int) -> SteelListResponse:
        with self.session_factory() as session:
            records = (
                session.query(Steelrecord)
                .filter(Steelrecord.seqNo == seq_no)
                .order_by(Steelrecord.id.desc())
                .all()
            )
            items = self._map_records(session, records, None)
            return SteelListResponse(count=len(items), items=items)

    def by_id(self, steel_id: int) -> SteelListResponse:
        with self.session_factory() as session:
            records = (
                session.query(Steelrecord)
                .filter(Steelrecord.id == steel_id)
                .order_by(Steelrecord.id.desc())
                .all()
            )
            items = self._map_records(session, records, None)
            return SteelListResponse(count=len(items), items=items)

    def by_steel_no(self, steel_no: str) -> SteelListResponse:
        with self.session_factory() as session:
            records = (
                session.query(Steelrecord)
                .filter(Steelrecord.steelID.like(f"%{steel_no}%"))
                .order_by(Steelrecord.seqNo.desc())
                .all()
            )
            items = self._map_records(session, records, None)
            return SteelListResponse(count=len(items), items=items)

    def by_date(self, start: datetime, end: datetime) -> SteelListResponse:
        with self.session_factory() as session:
            records = (
                session.query(Steelrecord)
                .filter(Steelrecord.detectTime >= start, Steelrecord.detectTime <= end)
                .order_by(Steelrecord.seqNo.desc())
                .all()
            )
            items = self._map_records(session, records, None)
            return SteelListResponse(count=len(items), items=items)

    def search(
        self,
        limit: int,
        seq_no: Optional[int],
        steel_no: Optional[str],
        start: Optional[datetime],
        end: Optional[datetime],
        desc: bool = True,
    ) -> SteelListResponse:
        """
        组合条件查询：支持序列号、钢板号模糊、时间范围。
        """
        with self.session_factory() as session:
            order_field = Steelrecord.seqNo.desc() if desc else Steelrecord.seqNo.asc()
            query = session.query(Steelrecord)

            if seq_no is not None:
                query = query.filter(Steelrecord.seqNo == seq_no)
            if steel_no:
                query = query.filter(Steelrecord.steelID.like(f"%{steel_no}%"))
            if start is not None:
                query = query.filter(Steelrecord.detectTime >= start)
            if end is not None:
                query = query.filter(Steelrecord.detectTime <= end)

            records = query.order_by(order_field).limit(limit).all()
            items = self._map_records(session, records, limit)
            return SteelListResponse(count=len(items), items=items)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _map_records(self, session: Session, records: Iterable[Steelrecord], limit: Optional[int]):
        selected = list(records)
        if limit:
            selected = selected[:limit]
        props = self._load_props(session, selected)
        return [self._to_model(rec, props.get(rec.steelID)) for rec in selected]

    def _load_props(self, session: Session, records: Iterable[Steelrecord]) -> dict[str, Rcvsteelprop]:
        steel_ids = {rec.steelID for rec in records if rec.steelID}
        if not steel_ids:
            return {}
        props = session.query(Rcvsteelprop).filter(Rcvsteelprop.steelID.in_(steel_ids)).all()
        return {prop.steelID: prop for prop in props}

    def _to_model(self, steel_obj: Steelrecord, extra: Optional[Rcvsteelprop]) -> SteelRecord:
        detect_time = getattr(steel_obj, "detectTime", None)
        return SteelRecord(
            seq_no=_coerce_int(getattr(steel_obj, "seqNo", None)),
            steel_id=str(getattr(steel_obj, "steelID", "")),
            steel_type=getattr(steel_obj, "steelType", None),
            produced_length=_coerce_int(getattr(steel_obj, "steelLen", None)),
            produced_width=_coerce_int(getattr(steel_obj, "width", None)),
            produced_thickness=_coerce_int(getattr(steel_obj, "thick", None)),
            defect_count=_coerce_int(getattr(steel_obj, "defectNum", None)),
            top_defect_count=None,
            bottom_defect_count=None,
            detect_time=detect_time,
            grade=_coerce_int(getattr(steel_obj, "grade", None)),
            warn=_coerce_int(getattr(steel_obj, "warn", None)),
            client=getattr(steel_obj, "client", None),
            hardness=_coerce_int(getattr(steel_obj, "hard", None)),
            ordered_length=_coerce_int(getattr(extra, "len", None)) if extra else None,
            ordered_width=_coerce_int(getattr(extra, "width", None)) if extra else None,
            ordered_thickness=_coerce_int(getattr(extra, "thick", None)) if extra else None,
        )
