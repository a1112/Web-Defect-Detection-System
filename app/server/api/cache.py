from __future__ import annotations

import json
import os
import shutil
import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.server import deps
from app.server.api.dependencies import get_image_service
from app.server.db.models.ncdplate import Steelrecord
from app.server.db.models.rbac import CacheRecord
from app.server.services.image_service import ImageService
from app.server.config.settings import CURRENT_DIR, DEFAULT_CONFIG_NAME, ensure_current_config_dir
from pathlib import Path


router = APIRouter(prefix="/api")

LINE_KEY_ENV = "DEFECT_LINE_KEY"
LINE_NAME_ENV = "DEFECT_LINE_NAME"


def _get_line_key() -> str:
    return os.getenv(LINE_KEY_ENV) or os.getenv(LINE_NAME_ENV) or "default"


def _load_server_config() -> dict:
    ensure_current_config_dir()
    config_path = CURRENT_DIR / DEFAULT_CONFIG_NAME
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_server_config(payload: dict) -> None:
    ensure_current_config_dir()
    config_path = CURRENT_DIR / DEFAULT_CONFIG_NAME
    config_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _resolve_seq_list(
    main_db: Session,
    mode: str,
    keep_last: Optional[int],
    start_seq: Optional[int],
    end_seq: Optional[int],
) -> list[int]:
    if mode == "keep_last" and keep_last:
        records = (
            main_db.query(Steelrecord.seqNo)
            .order_by(Steelrecord.seqNo.desc())
            .limit(int(keep_last))
            .all()
        )
        keep_set = {int(row.seqNo) for row in records}
        all_seqs = (
            main_db.query(Steelrecord.seqNo)
            .order_by(Steelrecord.seqNo.desc())
            .all()
        )
        return [int(row.seqNo) for row in all_seqs if int(row.seqNo) not in keep_set]
    if mode == "range" and start_seq is not None and end_seq is not None:
        records = (
            main_db.query(Steelrecord.seqNo)
            .filter(Steelrecord.seqNo >= int(start_seq), Steelrecord.seqNo <= int(end_seq))
            .order_by(Steelrecord.seqNo.desc())
            .all()
        )
        return [int(row.seqNo) for row in records]
    if mode == "all":
        records = (
            main_db.query(Steelrecord.seqNo)
            .order_by(Steelrecord.seqNo.desc())
            .all()
        )
        return [int(row.seqNo) for row in records]
    return []


class CacheSurfacePayload(BaseModel):
    surface: str
    view: str
    cached: bool = False
    image_missing: Optional[bool] = None
    stale: Optional[bool] = None
    tile_max_level: Optional[int] = None
    tile_size: Optional[int] = None
    defect_expand: Optional[int] = None
    defect_cache_enabled: Optional[bool] = None
    disk_cache_enabled: Optional[bool] = None
    updated_at: Optional[datetime] = None


class CacheRecordPayload(BaseModel):
    seq_no: int
    steel_no: Optional[str] = None
    detect_time: Optional[datetime] = None
    status: str
    surfaces: list[CacheSurfacePayload]


class CacheRecordsResponse(BaseModel):
    items: list[CacheRecordPayload]
    total: int
    max_seq: Optional[int] = None
    cache_range_min: Optional[int] = None
    expected_tile_max_level: Optional[int] = None
    expected_defect_expand: Optional[int] = None


class CacheScanRequest(BaseModel):
    seq_no: Optional[int] = Field(default=None, description="指定扫描的流水号")
    limit: Optional[int] = Field(default=None, description="扫描最近 N 条记录")


class CacheScanResponse(BaseModel):
    updated: int
    seq_nos: list[int]


class CachePrecacheRequest(BaseModel):
    seq_no: int
    levels: Optional[int] = None


class CachePrecacheResponse(BaseModel):
    ok: bool


class CacheStatusResponse(BaseModel):
    state: str
    message: str
    seq_no: Optional[int] = None
    surface: Optional[str] = None
    view: Optional[str] = None
    line_key: Optional[str] = None
    line_name: Optional[str] = None
    line_kind: Optional[str] = None
    pid: Optional[int] = None
    worker_per_surface: Optional[int] = None
    paused: bool = False
    task: Optional[dict] = None


class CacheSettingsPayload(BaseModel):
    memory_cache: dict[str, object]
    disk_cache: dict[str, object]


class CacheDeleteRequest(BaseModel):
    mode: str = Field(description="all | keep_last | range")
    keep_last: Optional[int] = None
    start_seq: Optional[int] = None
    end_seq: Optional[int] = None


class CacheDeleteResponse(BaseModel):
    ok: bool
    deleted: int


class CacheRebuildRequest(BaseModel):
    mode: str = Field(description="all | keep_last | range")
    keep_last: Optional[int] = None
    start_seq: Optional[int] = None
    end_seq: Optional[int] = None
    force: bool = Field(default=False)


class CacheRebuildResponse(BaseModel):
    ok: bool


class CacheMigrateRequest(BaseModel):
    top_root: Optional[str] = None
    bottom_root: Optional[str] = None


class CacheMigrateResponse(BaseModel):
    ok: bool


def _upsert_cache_record(
    session: Session,
    *,
    line_key: str,
    seq_no: int,
    surface: str,
    view: str,
    meta: Optional[dict],
    disk_cache_enabled: bool,
) -> bool:
    existing = (
        session.query(CacheRecord)
        .filter(
            CacheRecord.line_key == line_key,
            CacheRecord.seq_no == seq_no,
            CacheRecord.surface == surface,
            CacheRecord.view == view,
        )
        .one_or_none()
    )
    if not meta:
        if existing is not None:
            session.delete(existing)
            return True
        return False
    tile = meta.get("tile") or {}
    defects = meta.get("defects") or {}
    payload = {
        "line_key": line_key,
        "seq_no": seq_no,
        "surface": surface,
        "view": view,
        "tile_max_level": int(tile.get("max_level") or 0),
        "tile_size": int(tile.get("tile_size") or 0),
        "defect_expand": int(defects.get("expand") or 0),
        "defect_cache_enabled": bool(defects.get("enabled", True)),
        "disk_cache_enabled": bool(disk_cache_enabled),
        "meta_json": json.dumps(meta, ensure_ascii=False),
    }
    if existing is None:
        session.add(CacheRecord(**payload))
    else:
        for key, value in payload.items():
            setattr(existing, key, value)
    return True


@router.get("/cache/records", response_model=CacheRecordsResponse)
def list_cache_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    main_db: Session = Depends(deps.get_main_db),
    management_db: Session = Depends(deps.get_management_db),
    image_service: ImageService = Depends(get_image_service),
):
    line_key = _get_line_key()
    base_query = main_db.query(Steelrecord).order_by(Steelrecord.seqNo.desc())
    total = base_query.count()
    max_seq = main_db.query(func.max(Steelrecord.seqNo)).scalar()
    records = (
        base_query.offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    seq_nos = [int(record.seqNo) for record in records]
    cache_rows: list[CacheRecord] = []
    if seq_nos:
        cache_rows = (
            management_db.query(CacheRecord)
            .filter(CacheRecord.line_key == line_key, CacheRecord.seq_no.in_(seq_nos))
            .all()
        )
    cache_map: dict[int, dict[str, CacheRecord]] = {}
    disk_cache = image_service.settings.disk_cache
    for row in cache_rows:
        cache_map.setdefault(int(row.seq_no), {})[row.surface] = row

    max_records = int(disk_cache.disk_cache_max_records or 0)
    cache_range_min = None
    if max_records > 0 and max_seq:
        cache_range_min = int(max_seq) - max_records + 1
    expected_tile_max_level = image_service.disk_cache.max_level()
    expected_defect_expand = int(getattr(disk_cache, "defect_cache_expand", 0) or 0)
    view_dir = image_service.settings.images.default_view
    items: list[CacheRecordPayload] = []
    for record in records:
        seq_no = int(record.seqNo)
        surfaces: list[CacheSurfacePayload] = []
        surface_rows = cache_map.get(seq_no, {})
        cached_count = 0
        for surface in ("top", "bottom"):
            row = surface_rows.get(surface)
            cached = row is not None
            view_name = row.view if row is not None else view_dir
            stale = False
            if row is not None:
                if expected_tile_max_level and row.tile_max_level is not None:
                    stale = row.tile_max_level != expected_tile_max_level
                if expected_defect_expand and row.defect_expand is not None:
                    stale = stale or (row.defect_expand != expected_defect_expand)
            image_missing = False
            try:
                frames = image_service._list_frame_paths(surface, seq_no, view_name)
                image_missing = len(frames) == 0
            except FileNotFoundError:
                image_missing = True
            surfaces.append(
                CacheSurfacePayload(
                    surface=surface,
                    view=view_name,
                    cached=cached,
                    image_missing=image_missing,
                    stale=stale,
                    tile_max_level=row.tile_max_level if row else None,
                    tile_size=row.tile_size if row else None,
                    defect_expand=row.defect_expand if row else None,
                    defect_cache_enabled=row.defect_cache_enabled if row else None,
                    disk_cache_enabled=row.disk_cache_enabled if row else bool(disk_cache.disk_cache_enabled),
                    updated_at=row.updated_at if row else None,
                )
            )
            if cached:
                cached_count += 1
        status = "none"
        if cached_count == 1:
            status = "partial"
        elif cached_count >= 2:
            status = "complete"
        items.append(
            CacheRecordPayload(
                seq_no=seq_no,
                steel_no=record.steelID,
                detect_time=record.detectTime,
                status=status,
                surfaces=surfaces,
            )
        )

    return CacheRecordsResponse(
        items=items,
        total=total,
        max_seq=int(max_seq) if max_seq is not None else None,
        cache_range_min=cache_range_min,
        expected_tile_max_level=expected_tile_max_level,
        expected_defect_expand=expected_defect_expand,
    )


@router.post("/cache/scan", response_model=CacheScanResponse)
def scan_cache_records(
    payload: CacheScanRequest,
    image_service: ImageService = Depends(get_image_service),
    main_db: Session = Depends(deps.get_main_db),
    management_db: Session = Depends(deps.get_management_db),
):
    line_key = _get_line_key()
    view = image_service.settings.images.default_view
    disk_cache_enabled = bool(image_service.settings.disk_cache.disk_cache_enabled)

    seqs: list[int] = []
    if payload.seq_no is not None:
        seqs = [int(payload.seq_no)]
    elif payload.limit:
        records = (
            main_db.query(Steelrecord)
            .order_by(Steelrecord.seqNo.desc())
            .limit(int(payload.limit))
            .all()
        )
        seqs = [int(record.seqNo) for record in records]

    updated = 0
    for seq_no in seqs:
        meta_map = image_service.read_disk_cache_meta(seq_no)
        for surface in ("top", "bottom"):
            changed = _upsert_cache_record(
                management_db,
                line_key=line_key,
                seq_no=seq_no,
                surface=surface,
                view=view,
                meta=meta_map.get(surface),
                disk_cache_enabled=disk_cache_enabled,
            )
            if changed:
                updated += 1
    management_db.commit()
    return CacheScanResponse(updated=updated, seq_nos=seqs)


@router.post("/cache/precache", response_model=CachePrecacheResponse)
def precache_record(
    payload: CachePrecacheRequest,
    image_service: ImageService = Depends(get_image_service),
):
    image_service.precache_seq(int(payload.seq_no), levels=payload.levels)
    return CachePrecacheResponse(ok=True)


@router.websocket("/cache/ws")
async def cache_status_ws(websocket: WebSocket):
    await websocket.accept()
    image_service = get_image_service()
    last_payload: dict | None = None
    try:
        while True:
            status = image_service.get_cache_status()
            payload = {
                "state": str(status.get("state") or "ready"),
                "message": str(status.get("message") or "就绪"),
                "seq_no": status.get("seq_no"),
                "surface": status.get("surface"),
            }
            if payload != last_payload:
                await websocket.send_json(payload)
                last_payload = payload
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return


@router.get("/cache/status", response_model=CacheStatusResponse)
def get_cache_status(image_service: ImageService = Depends(get_image_service)):
    status = image_service.get_cache_status()
    return CacheStatusResponse(
        state=str(status.get("state") or "ready"),
        message=str(status.get("message") or "就绪"),
        seq_no=status.get("seq_no"),
        surface=status.get("surface"),
        view=status.get("view"),
        line_key=os.getenv(LINE_KEY_ENV) or os.getenv(LINE_NAME_ENV),
        line_name=os.getenv(LINE_NAME_ENV),
        line_kind=os.getenv("DEFECT_LINE_KIND") or "default",
        pid=os.getpid(),
        worker_per_surface=1,
        paused=bool(status.get("paused") or False),
        task=status.get("task"),
    )


@router.post("/cache/pause")
def pause_cache(image_service: ImageService = Depends(get_image_service)):
    image_service.pause_cache_tasks()
    return {"ok": True}


@router.post("/cache/resume")
def resume_cache(image_service: ImageService = Depends(get_image_service)):
    image_service.resume_cache_tasks()
    return {"ok": True}


@router.get("/cache/settings", response_model=CacheSettingsPayload)
def get_cache_settings(image_service: ImageService = Depends(get_image_service)):
    return CacheSettingsPayload(
        memory_cache=image_service.settings.memory_cache.model_dump(),
        disk_cache=image_service.settings.disk_cache.model_dump(),
    )


@router.put("/cache/settings", response_model=CacheSettingsPayload)
def update_cache_settings(
    payload: CacheSettingsPayload,
    image_service: ImageService = Depends(get_image_service),
):
    config = _load_server_config()
    memory_payload = payload.memory_cache if isinstance(payload.memory_cache, dict) else {}
    disk_payload = payload.disk_cache if isinstance(payload.disk_cache, dict) else {}
    config["memory_cache"] = {**(config.get("memory_cache") or {}), **memory_payload}
    config["disk_cache"] = {**(config.get("disk_cache") or {}), **disk_payload}
    _save_server_config(config)
    for key, value in memory_payload.items():
        setattr(image_service.settings.memory_cache, key, value)
    for key, value in disk_payload.items():
        setattr(image_service.settings.disk_cache, key, value)
    image_service.begin_cache_task("configuring", "?????????????????????")
    image_service.end_cache_task()
    return CacheSettingsPayload(
        memory_cache=image_service.settings.memory_cache.model_dump(),
        disk_cache=image_service.settings.disk_cache.model_dump(),
    )


@router.post("/cache/delete", response_model=CacheDeleteResponse)
def delete_cache_records(
    payload: CacheDeleteRequest,
    image_service: ImageService = Depends(get_image_service),
    main_db: Session = Depends(deps.get_main_db),
    management_db: Session = Depends(deps.get_management_db),
):
    line_key = _get_line_key()
    seqs = _resolve_seq_list(main_db, payload.mode, payload.keep_last, payload.start_seq, payload.end_seq)
    deleted = 0
    if seqs:
        image_service.enqueue_cache_delete(seqs)
        (
            management_db.query(CacheRecord)
            .filter(CacheRecord.line_key == line_key, CacheRecord.seq_no.in_(seqs))
            .delete(synchronize_session=False)
        )
        management_db.commit()
        deleted = len(seqs)
    return CacheDeleteResponse(ok=True, deleted=deleted)


@router.post("/cache/rebuild", response_model=CacheRebuildResponse)
def rebuild_cache_records(
    payload: CacheRebuildRequest,
    image_service: ImageService = Depends(get_image_service),
    main_db: Session = Depends(deps.get_main_db),
):
    seqs = _resolve_seq_list(main_db, payload.mode, payload.keep_last, payload.start_seq, payload.end_seq)
    if seqs:
        image_service.enqueue_cache_rebuild(seqs, force=payload.force)
    return CacheRebuildResponse(ok=True)


@router.post("/cache/migrate", response_model=CacheMigrateResponse)
def migrate_cache(
    payload: CacheMigrateRequest,
    image_service: ImageService = Depends(get_image_service),
):
    image_service.begin_cache_task("migrating", "缓存迁移中")
    try:
        config = _load_server_config()
        images_config = dict(config.get("images") or {})
        for surface, attr, new_root in (
            ("top", "disk_cache_top_root", payload.top_root),
            ("bottom", "disk_cache_bottom_root", payload.bottom_root),
        ):
            if not new_root:
                continue
            target_root = Path(new_root)
            target_root.mkdir(parents=True, exist_ok=True)
            old_root = image_service._cache_root(surface)
            if old_root.resolve() == target_root.resolve():
                images_config[attr] = str(target_root)
                continue
            view_dir = image_service.settings.images.default_view
            for entry in old_root.iterdir() if old_root.exists() else []:
                if not entry.is_dir():
                    continue
                cache_dir = entry / "cache" / view_dir
                if not cache_dir.exists():
                    continue
                dest_dir = target_root / entry.name / "cache" / view_dir
                dest_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(cache_dir.parent), str(dest_dir.parent))
            images_config[attr] = str(target_root)
            setattr(image_service.settings.images, attr, target_root)
        config["images"] = images_config
        _save_server_config(config)
    finally:
        image_service.end_cache_task()
    return CacheMigrateResponse(ok=True)
