from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.server.deps import get_defect_db
from app.server.db.models.extra.defect_annotation import DefectAnnotation
from app.server.schemas import (
    AnnotationBBox,
    DefectAnnotationCreate,
    DefectAnnotationItem,
    DefectAnnotationListResponse,
    DefectAnnotationUpdate,
)

router = APIRouter()


def _to_item(record: DefectAnnotation) -> DefectAnnotationItem:
    return DefectAnnotationItem(
        id=record.id,
        line_key=record.line_key,
        seq_no=record.seq_no,
        surface=record.surface,
        view=record.view,
        user=record.user,
        method=record.method,
        bbox=AnnotationBBox(
            left=record.left,
            top=record.top,
            right=record.right,
            bottom=record.bottom,
        ),
        class_id=record.class_id,
        class_name=record.class_name,
        mark=record.mark,
        export_payload=record.export_payload,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("/annotations", response_model=DefectAnnotationListResponse)
def list_annotations(
    line_key: Optional[str] = Query(default=None),
    seq_no: Optional[int] = Query(default=None),
    surface: Optional[str] = Query(default=None),
    view: Optional[str] = Query(default=None),
    session: Session = Depends(get_defect_db),
):
    query = session.query(DefectAnnotation)
    if line_key:
        query = query.filter(DefectAnnotation.line_key == line_key)
    if seq_no is not None:
        query = query.filter(DefectAnnotation.seq_no == seq_no)
    if surface:
        query = query.filter(DefectAnnotation.surface == surface)
    if view:
        query = query.filter(DefectAnnotation.view == view)
    items = [_to_item(row) for row in query.order_by(DefectAnnotation.id.desc())]
    return DefectAnnotationListResponse(items=items)


@router.post("/annotations", response_model=DefectAnnotationItem)
def create_annotation(
    payload: DefectAnnotationCreate,
    session: Session = Depends(get_defect_db),
):
    record = DefectAnnotation(
        line_key=payload.line_key,
        seq_no=payload.seq_no,
        surface=payload.surface,
        view=payload.view,
        user=payload.user,
        method=payload.method,
        left=payload.bbox.left,
        top=payload.bbox.top,
        right=payload.bbox.right,
        bottom=payload.bbox.bottom,
        class_id=payload.class_id,
        class_name=payload.class_name,
        mark=payload.mark,
        export_payload=payload.export_payload,
        extra=payload.extra,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return _to_item(record)


@router.post("/annotations/bulk", response_model=DefectAnnotationListResponse)
def create_annotations_bulk(
    payload: list[DefectAnnotationCreate],
    session: Session = Depends(get_defect_db),
):
    records: list[DefectAnnotation] = []
    for item in payload:
        record = DefectAnnotation(
            line_key=item.line_key,
            seq_no=item.seq_no,
            surface=item.surface,
            view=item.view,
            user=item.user,
            method=item.method,
            left=item.bbox.left,
            top=item.bbox.top,
            right=item.bbox.right,
            bottom=item.bbox.bottom,
            class_id=item.class_id,
            class_name=item.class_name,
            mark=item.mark,
            export_payload=item.export_payload,
            extra=item.extra,
        )
        records.append(record)
        session.add(record)
    session.commit()
    for record in records:
        session.refresh(record)
    return DefectAnnotationListResponse(items=[_to_item(row) for row in records])


@router.put("/annotations/{annotation_id}", response_model=DefectAnnotationItem)
def update_annotation(
    annotation_id: int,
    payload: DefectAnnotationUpdate,
    session: Session = Depends(get_defect_db),
):
    record = session.query(DefectAnnotation).filter(DefectAnnotation.id == annotation_id).one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Annotation not found")

    if payload.user is not None:
        record.user = payload.user
    if payload.method is not None:
        record.method = payload.method
    if payload.bbox is not None:
        record.left = payload.bbox.left
        record.top = payload.bbox.top
        record.right = payload.bbox.right
        record.bottom = payload.bbox.bottom
    if payload.class_id is not None:
        record.class_id = payload.class_id
    if payload.class_name is not None:
        record.class_name = payload.class_name
    if payload.mark is not None:
        record.mark = payload.mark
    if payload.export_payload is not None:
        record.export_payload = payload.export_payload
    if payload.extra is not None:
        record.extra = payload.extra

    session.commit()
    session.refresh(record)
    return _to_item(record)


@router.delete("/annotations/{annotation_id}")
def delete_annotation(
    annotation_id: int,
    session: Session = Depends(get_defect_db),
):
    record = session.query(DefectAnnotation).filter(DefectAnnotation.id == annotation_id).one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Annotation not found")
    session.delete(record)
    session.commit()
    return {"status": "ok"}
