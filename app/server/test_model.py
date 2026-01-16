from __future__ import annotations

import json
import logging
import random
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from collections import deque

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.server.config.settings import ServerSettings, CURRENT_DIR
from app.server.database import get_defect_session, get_main_session, _build_url
from app.server.net_table import load_map_payload
from app.server.status_service import get_status_service
import os

logger = logging.getLogger("test_model")
get_status_service().register_service("image_generate", label="图像生成", priority=90)

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "configs"
TEST_FLAG = CONFIG_DIR / "TEST_MODEL"
TESTDATA_DIR = REPO_ROOT / "TestData"
CONFIG_PATH = TESTDATA_DIR / "test_model_config.json"
LOG_PATH = TESTDATA_DIR / "test_model.log"

IMAGE_ROOT = TESTDATA_DIR / "Image"

router = APIRouter(prefix="/config/test_model")

DEFAULT_CONFIG = {
    "enabled": False,
    "record_interval_seconds": 5,
    "generate_defects": False,
    "defect_interval_seconds": 3,
    "defects_per_interval": 5,
    "length_range": [1000, 6000],
    "width_range": [800, 2000],
    "thickness_range": [5, 50],
    "frame_width": 16384,
    "frame_height": 1024,
    "source_seq": 1,
    "last_seq": None,
    "line_key": None,
    "remaining_records": None,
    "total_records": None,
    "image_count_min": 8,
    "image_count_max": 20,
    "image_interval_ms": 50,
    "views": ["2D"],
}

_worker_lock = threading.Lock()
_image_worker: threading.Thread | None = None
_defect_worker: threading.Thread | None = None
_worker_stop = threading.Event()
_status_lock = threading.Lock()
_status: dict[str, Any] = {
    "running": False,
    "current_seq": None,
    "current_steel_id": None,
    "remaining_records": 0,
    "current_image_index": None,
}
_log_lock = threading.Lock()
_log_items: deque[dict[str, Any]] = deque(maxlen=500)
_log_counter = 0


def _ensure_enabled() -> None:
    if os.getenv("DEFECT_TEST_MODE", "").strip().lower() in {"1", "true", "yes", "y", "on"}:
        return
    if not TEST_FLAG.exists():
        raise HTTPException(status_code=404, detail="TEST_MODEL not enabled")


def _load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return dict(DEFAULT_CONFIG)
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULT_CONFIG)
    merged = dict(DEFAULT_CONFIG)
    merged.update(payload if isinstance(payload, dict) else {})
    if "generate_defects" not in merged:
        merged["generate_defects"] = bool(merged.get("auto_add_defects"))
    if merged.get("last_seq") in (None, "", 0):
        merged["last_seq"] = _resolve_last_seq(merged)
    return merged


def _save_config(payload: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_log(message: str, payload: dict[str, Any] | None = None) -> None:
    global _log_counter
    _log_counter += 1
    entry = {
        "id": _log_counter,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "message": message,
        "data": payload or {},
    }
    with _log_lock:
        _log_items.appendleft(entry)
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info("%s | %s", message, payload or {})


def _update_image_status(state: str, seq_no: int | None = None, index: int | None = None, message: str | None = None) -> None:
    try:
        data: dict[str, Any] = {}
        if seq_no is not None:
            data["seq_no"] = seq_no
        if index is not None:
            data["image_index"] = index
        get_status_service().update_service(
            "image_generate",
            state=state,
            message=message or ("系统就绪" if state == "ready" else "图像生成中"),
            data=data,
        )
    except Exception:
        return


def _resolve_host_token(settings: ServerSettings) -> str:
    env_host = os.getenv("DEFECT_LINE_HOST")
    if env_host and env_host.strip():
        return env_host.strip()
    db_host = settings.database.host or "127.0.0.1"
    if db_host and db_host != "{ip}":
        return str(db_host)
    return "127.0.0.1"


def _resolve_line_context(config: dict[str, Any]) -> tuple[str | None, str | None, list[str]]:
    root, payload = load_map_payload()
    lines = payload.get("lines") or []
    views = payload.get("views") or {}
    view_keys = list(views.keys()) if isinstance(views, dict) and views else ["2D"]
    line_key = config.get("line_key")
    line = None
    if line_key:
        line = next(
            (item for item in lines if str(item.get("key") or item.get("name") or "") == str(line_key)),
            None,
        )
    if not line and lines:
        line = next((item for item in lines if (item.get("mode") or "direct") == "direct"), lines[0])
        line_key = str(line.get("key") or line.get("name") or "")
    ip = None
    if line:
        ip = line.get("ip") or line.get("host")
    return line_key, ip, view_keys


def _resolved_settings(config: dict[str, Any] | None = None) -> ServerSettings:
    config = config or {}
    line_key, ip, view_keys = _resolve_line_context(config)
    view_name = "2D" if "2D" in view_keys else (view_keys[0] if view_keys else "2D")
    if line_key:
        candidate = CURRENT_DIR / "generated" / line_key / view_name / "server.json"
        if candidate.exists():
            return ServerSettings.load(explicit_path=candidate)

    settings = ServerSettings.load()
    host = ip or _resolve_host_token(settings)
    db_host = settings.database.host
    if isinstance(db_host, str) and "{ip}" in db_host:
        db_host = db_host.replace("{ip}", host)
        settings = settings.model_copy(
            update={"database": settings.database.model_copy(update={"host": db_host})}
        )
    images = settings.images.model_copy(
        update={
            "top_root": Path(str(settings.images.top_root).replace("{ip}", host)),
            "bottom_root": Path(str(settings.images.bottom_root).replace("{ip}", host)),
            "disk_cache_top_root": Path(str(settings.images.disk_cache_top_root).replace("{ip}", host))
            if settings.images.disk_cache_top_root
            else settings.images.disk_cache_top_root,
            "disk_cache_bottom_root": Path(str(settings.images.disk_cache_bottom_root).replace("{ip}", host))
            if settings.images.disk_cache_bottom_root
            else settings.images.disk_cache_bottom_root,
        }
    )
    return settings.model_copy(update={"images": images})


def _image_roots(config: dict[str, Any] | None = None) -> tuple[Path, Path]:
    settings = _resolved_settings(config)
    host = _resolve_host_token(settings)
    def _resolve(path: Path) -> Path:
        raw = str(path)
        if "{ip}" in raw:
            raw = raw.replace("{ip}", host)
        return Path(raw)
    return _resolve(settings.images.top_root), _resolve(settings.images.bottom_root)


def _resolve_image_index_max(seq_no: int, config: dict[str, Any]) -> int | None:
    views = config.get("views") or ["2D"]
    if not views:
        views = ["2D"]
    top_root, _ = _image_roots(config)
    target_dir = top_root / str(seq_no)
    if not target_dir.exists():
        return None
    max_index = None
    for view in views:
        view_dir = target_dir / view
        if not view_dir.exists():
            continue
        for entry in view_dir.iterdir():
            if not entry.is_file() or entry.suffix.lower() != ".jpg":
                continue
            try:
                idx = int(entry.stem)
            except ValueError:
                continue
            max_index = idx if max_index is None else max(max_index, idx)
    return max_index


def _resolve_last_seq(config: dict[str, Any] | None = None) -> int:
    settings = _resolved_settings(config)
    max_seq = 0
    try:
        main_session = get_main_session(settings)
        try:
            max_seq = main_session.execute(text("SELECT MAX(SeqNo) FROM steelrecord")).scalar() or 0
        finally:
            main_session.close()
    except Exception:
        max_seq = 0
    if max_seq > 0:
        return int(max_seq)
    top_root, bottom_root = _image_roots(config)
    candidates: list[int] = []
    for root in (top_root, bottom_root):
        if not root.exists():
            continue
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            try:
                candidates.append(int(entry.name))
            except ValueError:
                continue
    return max(candidates) if candidates else int(DEFAULT_CONFIG.get("source_seq") or 1)


def _copy_images(seq_no: int, config: dict[str, Any], *, image_count: int) -> int | None:
    def _sort_key(path: Path) -> tuple[int, int | str]:
        try:
            return (0, int(path.stem))
        except ValueError:
            return (1, path.stem)

    started_at = time.time()
    source_seq = int(config.get("source_seq") or 1)
    views = config.get("views") or ["2D"]
    image_interval_ms = int(config.get("image_interval_ms") or 0)
    top_root, bottom_root = _image_roots(config)
    log_summary: dict[str, Any] = {
        "seq_no": seq_no,
        "views": views,
        "surfaces": [],
        "image_count": image_count,
        "samples": [],
        "missing_views": [],
        "image_interval_ms": image_interval_ms,
    }

    surface_info: dict[str, dict[str, Any]] = {}
    for root in (top_root, bottom_root):
        surface = "top" if root == top_root else "bottom"
        source_dir = root / str(source_seq)
        if not source_dir.exists():
            raise FileNotFoundError(source_dir)
        view_files: dict[str, list[Path]] = {}
        available_counts: list[int] = []
        for view in views:
            view_dir = source_dir / view
            if not view_dir.exists():
                log_summary["missing_views"].append(f"{surface}:{view}")
                view_files[view] = []
                continue
            files = sorted(
                [p for p in view_dir.iterdir() if p.is_file() and p.suffix.lower() == ".jpg"],
                key=_sort_key,
            )
            if not files:
                log_summary["missing_views"].append(f"{surface}:{view}")
                view_files[view] = []
                continue
            view_files[view] = files
            available_counts.append(len(files))
        surface_info[surface] = {
            "root": root,
            "view_files": view_files,
            "available_count": min(available_counts) if available_counts else 0,
        }

    available_per_surface = [
        info["available_count"]
        for info in surface_info.values()
        if int(info.get("available_count") or 0) > 0
    ]
    if not available_per_surface:
        log_summary["elapsed_seconds"] = round(time.time() - started_at, 2)
        _append_log("添加图像", log_summary)
        return None
    effective_count = max(1, min(image_count, min(available_per_surface)))

    selected_by_surface: dict[str, dict[str, list[Path]]] = {}
    for surface, info in surface_info.items():
        view_files = info.get("view_files") or {}
        selected_by_view: dict[str, list[Path]] = {}
        for view, files in view_files.items():
            if not files:
                selected_by_view[view] = []
                continue
            mid = len(files) // 2
            start = max(0, mid - effective_count // 2)
            selected_by_view[view] = files[start : start + effective_count]
        selected_by_surface[surface] = selected_by_view

    max_existing = 0
    for surface, info in surface_info.items():
        root = info["root"]
        target_dir = root / str(seq_no)
        for view in views:
            target_view = target_dir / view
            if not target_view.exists():
                continue
            for existing in target_view.iterdir():
                if not existing.is_file() or existing.suffix.lower() != ".jpg":
                    continue
                try:
                    max_existing = max(max_existing, int(existing.stem))
                except ValueError:
                    continue
    start_index = max_existing + 1
    latest_index: int | None = None

    for offset in range(effective_count):
        current_index = start_index + offset
        for surface, info in surface_info.items():
            root = info["root"]
            target_dir = root / str(seq_no)
            surface_summary = next(
                (item for item in log_summary["surfaces"] if item.get("surface") == surface),
                None,
            )
            if not surface_summary:
                surface_summary = {"surface": surface, "files": 0}
                log_summary["surfaces"].append(surface_summary)
            for view in views:
                selected = selected_by_surface.get(surface, {}).get(view) or []
                if offset >= len(selected):
                    continue
                target_view = target_dir / view
                target_view.mkdir(parents=True, exist_ok=True)
                target_path = target_view / f"{current_index}.jpg"
                shutil.copy2(selected[offset], target_path)
                surface_summary["files"] += 1
                if len(log_summary["samples"]) < 3:
                    log_summary["samples"].append(str(target_path))
                latest_index = current_index if latest_index is None else max(latest_index, current_index)
        if image_interval_ms > 0:
            time.sleep(image_interval_ms / 1000.0)

    for surface_summary in log_summary["surfaces"]:
        surface_summary["index_start"] = start_index
        surface_summary["index_end"] = start_index + effective_count - 1
    log_summary["image_count"] = effective_count
    log_summary["elapsed_seconds"] = round(time.time() - started_at, 2)

    record_path = (top_root / str(seq_no)) / "record.json"
    record_payload = {
        "seq_no": seq_no,
        "views": views,
        "image_count": log_summary["image_count"],
        "imgNum": log_summary["image_count"],
        "img_num": log_summary["image_count"],
        "surfaces": log_summary["surfaces"],
        "latest_index": latest_index,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    record_path.write_text(json.dumps(record_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for surface_root in (top_root, bottom_root):
        seq_dir = surface_root / str(seq_no)
        for view in views:
            view_dir = seq_dir / view
            view_dir.mkdir(parents=True, exist_ok=True)
            view_record = view_dir / "record.json"
            view_record.write_text(
                json.dumps(record_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    _append_log("添加图像", log_summary)
    return latest_index


def _insert_steel_record(seq_no: int, config: dict[str, Any]) -> str:
    length = random.randint(*config.get("length_range", [1000, 6000]))
    width = random.randint(*config.get("width_range", [800, 2000]))
    thickness = random.randint(*config.get("thickness_range", [5, 50]))
    defect_num = 0
    steel_id = f"TEST-{seq_no:06d}"
    detect_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    settings = _resolved_settings(config)
    session = get_main_session(settings)
    try:
        session.execute(
            text(
                """
                INSERT INTO steelrecord
                (SeqNo, SteelID, SteelType, SteelLen, Width, Thick, DefectNum, DetectTime, Grade, warn, steelOut, cycle, client)
                VALUES (:seq_no, :steel_id, :steel_type, :length, :width, :thickness, :defect_num, :detect_time, :grade, :warn, :steel_out, :cycle, :client)
                """
            ),
            {
                "seq_no": seq_no,
                "steel_id": steel_id,
                "steel_type": "TEST",
                "length": length,
                "width": width,
                "thickness": thickness,
                "defect_num": defect_num,
                "detect_time": detect_time,
                "grade": 1,
                "warn": 0,
                "steel_out": 0,
                "cycle": 0,
                "client": "TEST",
            },
        )
        session.commit()
    finally:
        session.close()
    return steel_id


def _insert_defects(
    seq_no: int,
    config: dict[str, Any],
    *,
    img_index_max: int | None = None,
    count: int | None = None,
) -> None:
    max_per_interval = int(config.get("defects_per_interval") or 0)
    target_max = int(count) if count is not None else max_per_interval
    if target_max <= 0:
        return
    defect_count = random.randint(0, target_max)
    if defect_count <= 0:
        _append_log("生成缺陷", {"seq_no": seq_no, "defect_count": 0})
        return
    frame_width = int(config.get("frame_width") or 16384)
    frame_height = int(config.get("frame_height") or 1024)
    img_index_min = None
    img_index_latest = None
    if img_index_max is not None and int(img_index_max) > 0:
        img_index_latest = int(img_index_max)
        img_index_min = img_index_latest
        img_index_max = img_index_latest
    settings = _resolved_settings(config)
    session = get_defect_session(settings)
    try:
        session.execute(text("DELETE FROM camdefect1 WHERE seqNo = :seq_no"), {"seq_no": seq_no})
        session.execute(text("DELETE FROM camdefect2 WHERE seqNo = :seq_no"), {"seq_no": seq_no})
        session.execute(text("DELETE FROM camdefectsum1 WHERE seqNo = :seq_no"), {"seq_no": seq_no})
        session.execute(text("DELETE FROM camdefectsum2 WHERE seqNo = :seq_no"), {"seq_no": seq_no})
        class_counts_top: dict[int, int] = {}
        class_counts_bottom: dict[int, int] = {}
        for surface_table, class_counts in (("camdefect1", class_counts_top), ("camdefect2", class_counts_bottom)):
            for idx in range(defect_count):
                defect_class = random.randint(1, 10)
                left = random.randint(0, max(0, frame_width - 200))
                top = random.randint(0, max(0, frame_height - 200))
                right = left + random.randint(20, 200)
                bottom = top + random.randint(20, 200)
                img_index = None
                if img_index_max is not None:
                    img_index = img_index_latest
                session.execute(
                    text(
                        f"""
                        INSERT INTO {surface_table}
                        (defectID, camNo, seqNo, imgIndex, defectClass, leftInImg, rightInImg, topInImg, bottomInImg,
                         leftInSrcImg, rightInSrcImg, topInSrcImg, bottomInSrcImg, leftInObj, rightInObj, topInObj, bottomInObj,
                         grade, area, leftToEdge, rightToEdge, cycle)
                        VALUES
                        (:defect_id, :cam_no, :seq_no, :img_index, :defect_class, :left_img, :right_img, :top_img, :bottom_img,
                         :left_src, :right_src, :top_src, :bottom_src, :left_obj, :right_obj, :top_obj, :bottom_obj,
                         :grade, :area, :left_edge, :right_edge, :cycle)
                        """
                    ),
                    {
                        "defect_id": idx + 1,
                        "cam_no": 1 if surface_table == "camdefect1" else 2,
                        "seq_no": seq_no,
                        "img_index": int(img_index) if img_index is not None else random.randint(1, 50),
                        "defect_class": defect_class,
                        "left_img": left,
                        "right_img": right,
                        "top_img": top,
                        "bottom_img": bottom,
                        "left_src": left,
                        "right_src": right,
                        "top_src": top,
                        "bottom_src": bottom,
                        "left_obj": left,
                        "right_obj": right,
                        "top_obj": top,
                        "bottom_obj": bottom,
                        "grade": random.randint(1, 3),
                        "area": (right - left) * (bottom - top),
                        "left_edge": left,
                        "right_edge": frame_width - right,
                        "cycle": 0,
                    },
                )
                class_counts[defect_class] = class_counts.get(defect_class, 0) + 1
        for cls, count in class_counts_top.items():
            session.execute(
                text("INSERT INTO camdefectsum1 (seqNo, defectClass, defectNum) VALUES (:seq_no, :cls, :count)"),
                {"seq_no": seq_no, "cls": cls, "count": count},
            )
        for cls, count in class_counts_bottom.items():
            session.execute(
                text("INSERT INTO camdefectsum2 (seqNo, defectClass, defectNum) VALUES (:seq_no, :cls, :count)"),
                {"seq_no": seq_no, "cls": cls, "count": count},
            )
        session.commit()
    finally:
        session.close()
    payload = {"seq_no": seq_no, "defect_count": defect_count, "surfaces": ["top", "bottom"]}
    if img_index_max is not None:
        payload["image_index"] = img_index_latest
        payload["img_index_min"] = img_index_min
        payload["img_index_max"] = img_index_max
    _append_log("生成缺陷", payload)


def _next_seq(config: dict[str, Any]) -> int:
    seq = int(config.get("last_seq") or config.get("source_seq") or 1) + 1
    config["last_seq"] = seq
    _save_config(config)
    return seq


def _set_status(**kwargs: Any) -> None:
    with _status_lock:
        _status.update(kwargs)


def _get_status() -> dict[str, Any]:
    with _status_lock:
        return dict(_status)


def _image_loop() -> None:
    while not _worker_stop.is_set():
        loop_start = time.time()
        config = _load_config()
        if not config.get("enabled"):
            _update_image_status("ready")
            time.sleep(1)
            continue
        remaining_raw = config.get("remaining_records")
        total_raw = config.get("total_records")
        remaining = int(remaining_raw) if remaining_raw is not None else None
        total = int(total_raw) if total_raw is not None else None
        if remaining is not None and remaining <= 0 and (total or 0) > 0:
            config["enabled"] = False
            _save_config(config)
            _set_status(running=False, remaining_records=0)
            continue
        min_count = int(config.get("image_count_min") or 1)
        max_count = int(config.get("image_count_max") or min_count)
        if max_count < min_count:
            max_count = min_count
        image_count = random.randint(min_count, max_count)
        seq_no = None
        steel_id = None
        try:
            seq_no = _next_seq(config)
            _set_status(running=True, current_seq=seq_no, current_steel_id=None, current_image_index=None)
            latest_index = _copy_images(seq_no, config, image_count=image_count)
            steel_id = _insert_steel_record(seq_no, config)
            _append_log(
                "生成记录",
                {"seq_no": seq_no, "steel_id": steel_id, "image_count": image_count},
            )
            _set_status(current_image_index=latest_index)
            _update_image_status(
                "running",
                seq_no=seq_no,
                index=latest_index,
                message=f"图像生成中：{seq_no}-{latest_index}" if latest_index is not None else "图像生成中",
            )
            try:
                get_status_service().append_log(
                    "image_generate",
                    level="info",
                    message="生成图像",
                    data={"seq_no": seq_no, "image_index": latest_index, "image_count": image_count},
                )
            except Exception:
                pass
        except Exception as exc:
            _append_log("生成失败", {"error": str(exc)})
            logger.exception("auto image generate failed")
        if remaining is not None and remaining > 0:
            config["remaining_records"] = remaining - 1
            _save_config(config)
        _set_status(
            running=True,
            current_seq=seq_no,
            current_steel_id=steel_id,
            remaining_records=config.get("remaining_records"),
        )
        interval = max(1, int(config.get("record_interval_seconds") or 5))
        elapsed = time.time() - loop_start
        sleep_seconds = max(0.0, interval - elapsed)
        time.sleep(sleep_seconds)


def _defect_loop() -> None:
    last_defect_ts = 0.0
    while not _worker_stop.is_set():
        config = _load_config()
        if not config.get("enabled") or not config.get("generate_defects"):
            time.sleep(1)
            continue
        now = time.time()
        interval = int(config.get("defect_interval_seconds") or 0)
        if interval <= 0 or now - last_defect_ts >= interval:
            status_snapshot = _get_status()
            target_seq = int(
                status_snapshot.get("current_seq")
                or config.get("last_seq")
                or config.get("source_seq")
                or 1
            )
            current_index = status_snapshot.get("current_image_index")
            if current_index is None:
                current_index = _resolve_image_index_max(target_seq, config)
            try:
                _insert_defects(target_seq, config, img_index_max=current_index)
                last_defect_ts = now
            except Exception as exc:
                _append_log("生成失败", {"error": str(exc)})
                logger.exception("auto defect generate failed")
        time.sleep(0.2)


def _ensure_worker() -> None:
    global _image_worker, _defect_worker
    with _worker_lock:
        if _image_worker and _image_worker.is_alive() and _defect_worker and _defect_worker.is_alive():
            return
        _worker_stop.clear()
        if not _image_worker or not _image_worker.is_alive():
            _image_worker = threading.Thread(target=_image_loop, daemon=True)
            _image_worker.start()
        if not _defect_worker or not _defect_worker.is_alive():
            _defect_worker = threading.Thread(target=_defect_loop, daemon=True)
            _defect_worker.start()


class ConfigPayload(BaseModel):
    enabled: bool | None = None
    record_interval_seconds: int | None = None
    generate_defects: bool | None = None
    defect_interval_seconds: int | None = None
    defects_per_interval: int | None = None
    length_range: list[int] | None = None
    width_range: list[int] | None = None
    thickness_range: list[int] | None = None
    frame_width: int | None = None
    frame_height: int | None = None
    source_seq: int | None = None
    views: list[str] | None = None
    line_key: str | None = None
    image_count_min: int | None = None
    image_count_max: int | None = None
    image_interval_ms: int | None = None
    total_records: int | None = None


class AddImagesPayload(BaseModel):
    count: int = Field(default=1, ge=1, le=200)
    image_count: int | None = None


class AddDefectsPayload(BaseModel):
    seq_no: int | None = None
    count: int | None = None


class RangePayload(BaseModel):
    start_seq: int | None = None
    end_seq: int | None = None


@router.get("/status")
def status() -> dict[str, Any]:
    _ensure_enabled()
    status_payload = _get_status()
    config = _load_config()
    settings = _resolved_settings(config)
    main_session = get_main_session(settings)
    defect_session = get_defect_session(settings)
    try:
        steel_count = main_session.execute(text("SELECT COUNT(*) FROM steelrecord")).scalar() or 0
        max_seq = main_session.execute(text("SELECT MAX(SeqNo) FROM steelrecord")).scalar() or 0
        defect_count = (
            (defect_session.execute(text("SELECT COUNT(*) FROM camdefect1")).scalar() or 0)
            + (defect_session.execute(text("SELECT COUNT(*) FROM camdefect2")).scalar() or 0)
        )
    finally:
        main_session.close()
        defect_session.close()
    current_seq = status_payload.get("current_seq")
    if not current_seq:
        current_seq = config.get("last_seq") or max_seq
    current_index = status_payload.get("current_image_index")
    if current_index is None and current_seq:
        current_index = _resolve_image_index_max(int(current_seq), config)
    return {
        "enabled": True,
        "running": bool(
            config.get("enabled")
            and ((_image_worker and _image_worker.is_alive()) or (_defect_worker and _defect_worker.is_alive()))
        ),
        "current_seq": current_seq,
        "current_steel_id": status_payload.get("current_steel_id"),
        "remaining_records": status_payload.get("remaining_records") if status_payload.get("remaining_records") is not None else config.get("remaining_records"),
        "current_image_index": current_index,
        "steel_count": steel_count,
        "max_seq": max_seq,
        "defect_count": defect_count,
        "database_name": settings.database.database_type,
        "database_url": _build_url(settings.database, settings.database.database_type),
    }


@router.get("/config")
def get_config() -> dict[str, Any]:
    _ensure_enabled()
    return _load_config()


@router.put("/config")
def update_config(payload: ConfigPayload) -> dict[str, Any]:
    _ensure_enabled()
    config = _load_config()
    for key, value in payload.dict(exclude_unset=True).items():
        config[key] = value
    _save_config(config)
    _append_log("更新配置", {"fields": list(payload.dict(exclude_unset=True).keys())})
    return config


@router.post("/start")
def start() -> dict[str, Any]:
    _ensure_enabled()
    config = _load_config()
    config["enabled"] = True
    total = config.get("total_records")
    if total is not None and int(total) > 0:
        config["remaining_records"] = int(total)
    elif total is None:
        config["remaining_records"] = None
    _save_config(config)
    _ensure_worker()
    _set_status(running=True, remaining_records=config.get("remaining_records"))
    _append_log("开始自动生成", {"total_records": config.get("total_records")})
    _update_image_status("running", message="图像生成中")
    return {"ok": True}


@router.post("/stop")
def stop() -> dict[str, Any]:
    _ensure_enabled()
    config = _load_config()
    config["enabled"] = False
    _save_config(config)
    _worker_stop.set()
    _set_status(running=False)
    _append_log("停止自动生成")
    _update_image_status("ready", message="生成完成")
    return {"ok": True}


@router.post("/add_images")
def add_images(payload: AddImagesPayload) -> dict[str, Any]:
    _ensure_enabled()
    config = _load_config()
    seqs: list[int] = []
    min_count = int(config.get("image_count_min") or 1)
    max_count = int(config.get("image_count_max") or min_count)
    if max_count < min_count:
        max_count = min_count
    image_count = payload.image_count or random.randint(min_count, max_count)
    for _ in range(payload.count):
        seq_no = _next_seq(config)
        latest_index = _copy_images(seq_no, config, image_count=image_count)
        _insert_steel_record(seq_no, config)
        _set_status(current_image_index=latest_index)
        seqs.append(seq_no)
    _append_log("手动新增图像记录", {"seqs": seqs, "image_count": image_count})
    return {"ok": True, "seqs": seqs}


@router.post("/add_image_one")
def add_image_one() -> dict[str, Any]:
    _ensure_enabled()
    config = _load_config()
    seq_no = _next_seq(config)
    latest_index = _copy_images(seq_no, config, image_count=1)
    _insert_steel_record(seq_no, config)
    _set_status(current_image_index=latest_index)
    _append_log("手动生成单张图像", {"seq_no": seq_no})
    return {"ok": True, "seq_no": seq_no}


@router.post("/add_defects")
def add_defects(payload: AddDefectsPayload) -> dict[str, Any]:
    _ensure_enabled()
    config = _load_config()
    seq_no = payload.seq_no or int(config.get("last_seq") or config.get("source_seq") or 1)
    current_index = _get_status().get("current_image_index")
    _insert_defects(seq_no, config, img_index_max=current_index, count=payload.count)
    _save_config(config)
    _append_log("手动生成缺陷", {"seq_no": seq_no, "defect_count": payload.count})
    return {"ok": True, "seq_no": seq_no}


@router.post("/delete_images")
def delete_images(payload: RangePayload) -> dict[str, Any]:
    _ensure_enabled()
    config = _load_config()
    source_seq = int(config.get("source_seq") or 1)
    start_seq = payload.start_seq
    end_seq = payload.end_seq
    deleted: list[int] = []
    top_root, bottom_root = _image_roots(config)
    for root in (top_root, bottom_root):
        if not root.exists():
            continue
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            try:
                seq = int(entry.name)
            except ValueError:
                continue
            if seq == source_seq:
                continue
            if start_seq is not None and seq < start_seq:
                continue
            if end_seq is not None and seq > end_seq:
                continue
            shutil.rmtree(entry, ignore_errors=True)
            deleted.append(seq)
    _append_log("删除图像", {"start_seq": start_seq, "end_seq": end_seq, "deleted": deleted})
    return {"ok": True, "deleted": deleted}


@router.post("/clear_database")
def clear_database() -> dict[str, Any]:
    _ensure_enabled()
    settings = _resolved_settings()
    main_session = get_main_session(settings)
    defect_session = get_defect_session(settings)
    try:
        main_session.execute(text("DELETE FROM steelrecord"))
        main_session.commit()
        defect_session.execute(text("DELETE FROM camdefect1"))
        defect_session.execute(text("DELETE FROM camdefect2"))
        defect_session.execute(text("DELETE FROM camdefectsum1"))
        defect_session.execute(text("DELETE FROM camdefectsum2"))
        defect_session.commit()
    finally:
        main_session.close()
        defect_session.close()
    _append_log("清空数据库")
    return {"ok": True}


@router.get("/logs")
def get_logs(limit: int = 200, cursor: int = 0) -> dict[str, Any]:
    _ensure_enabled()
    with _log_lock:
        capped = max(1, min(limit, 500))
        if cursor <= 0:
            items = list(reversed(_log_items))[-capped:]
        else:
            items = [item for item in reversed(_log_items) if int(item.get("id") or 0) > cursor]
        latest_id = _log_items[0]["id"] if _log_items else cursor
    return {"items": items, "cursor": latest_id}


@router.post("/logs/clear")
def clear_logs() -> dict[str, Any]:
    _ensure_enabled()
    with _log_lock:
        _log_items.clear()
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOG_PATH.write_text("", encoding="utf-8")
    return {"ok": True}
