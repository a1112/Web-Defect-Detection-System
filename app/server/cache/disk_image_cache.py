from __future__ import annotations

import json
import logging
import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiskCacheKey:
    surface_root: Path
    seq_no: int
    view: str


class DiskImageCache:
    """
    File-level cache for tiles and defect crops.
    Layout (example):
      {cache_root}/{seq_no}/cache/{view}/
        cache.json
        tile/{level}/{orientation}_{tile_x}_{tile_y}.jpg
        defects/{surface}/{defect_id}.jpg
    """

    def __init__(
        self,
        *,
        enabled: bool,
        read_only: bool = False,
        flat_layout: bool = False,
        max_tiles: int,
        max_defects: int,
        defect_expand: int,
        tile_size: int,
        frame_width: int,
        frame_height: int,
        view_name: str,
    ):
        self.enabled = enabled
        self.read_only = read_only
        self.flat_layout = flat_layout
        self.max_tiles = max_tiles
        self.max_defects = max_defects
        self.defect_expand = defect_expand
        self.tile_size = tile_size
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.view_name = view_name
        self._lock = threading.Lock()

    def max_level(self) -> int:
        if self.frame_height <= 0 or self.frame_width <= 0:
            return 0
        ratio = self.frame_width / self.frame_height
        if ratio <= 1:
            return 0
        return int(math.ceil(math.log(ratio, 2)))

    def cache_dir(self, cache_root: Path, seq_no: int, view: Optional[str]) -> Path:
        view_dir = view or self.view_name
        if self.flat_layout:
            return cache_root / "cache" / view_dir
        return cache_root / str(seq_no) / "cache" / view_dir

    def tile_path(
        self,
        cache_root: Path,
        seq_no: int,
        *,
        view: Optional[str],
        level: int,
        orientation: str,
        tile_x: int,
        tile_y: int,
    ) -> Path:
        base = self.cache_dir(cache_root, seq_no, view)
        return base / "tile" / str(level) / f"{orientation}_{tile_x}_{tile_y}.jpg"

    def defect_path(
        self,
        cache_root: Path,
        seq_no: int,
        *,
        view: Optional[str],
        surface: str,
        defect_id: str,
    ) -> Path:
        base = self.cache_dir(cache_root, seq_no, view)
        # 新目录规范：cache/{view}/defect/{seq}_{surface}_{left}_{top}_{w}_{h}_{expand}.jpg
        # 这里 defect_id 已经是完整的文件名主体。
        return base / "defect" / f"{defect_id}.jpg"

    def read_tile(
        self,
        cache_root: Path,
        seq_no: int,
        *,
        view: Optional[str],
        level: int,
        orientation: str,
        tile_x: int,
        tile_y: int,
    ) -> Optional[bytes]:
        if not self.enabled:
            return None
        path = self.tile_path(
            cache_root,
            seq_no,
            view=view,
            level=level,
            orientation=orientation,
            tile_x=tile_x,
            tile_y=tile_y,
        )
        try:
            return path.read_bytes() if path.exists() else None
        except OSError:
            return None

    def write_tile(
        self,
        cache_root: Path,
        seq_no: int,
        *,
        view: Optional[str],
        level: int,
        orientation: str,
        tile_x: int,
        tile_y: int,
        payload: bytes,
    ) -> None:
        if not self.enabled or self.read_only:
            return
        path = self.tile_path(
            cache_root,
            seq_no,
            view=view,
            level=level,
            orientation=orientation,
            tile_x=tile_x,
            tile_y=tile_y,
        )
        self._atomic_write(path, payload)
        self._ensure_cache_json(cache_root, seq_no, view=view)

    def read_defect(
        self,
        cache_root: Path,
        seq_no: int,
        *,
        view: Optional[str],
        surface: str,
        defect_id: str,
    ) -> Optional[bytes]:
        if not self.enabled:
            return None
        base = self.cache_dir(cache_root, seq_no, view)
        path = base / "defect" / f"{defect_id}.jpg"
        try:
            return path.read_bytes() if path.exists() else None
        except OSError:
            return None

    def write_defect(
        self,
        cache_root: Path,
        seq_no: int,
        *,
        view: Optional[str],
        surface: str,
        defect_id: str,
        payload: bytes,
    ) -> None:
        if not self.enabled or self.read_only:
            return
        path = self.defect_path(cache_root, seq_no, view=view, surface=surface, defect_id=defect_id)
        self._atomic_write(path, payload)
        self._ensure_cache_json(cache_root, seq_no, view=view)

    def cleanup_seq(
        self,
        cache_root: Path,
        seq_no: int,
        *,
        view: Optional[str],
    ) -> None:
        if not self.enabled or self.read_only:
            return
        base = self.cache_dir(cache_root, seq_no, view)
        tile_dir = base / "tile"
        defect_dir = base / "defect"
        self._enforce_limit(tile_dir, self.max_tiles)
        self._enforce_limit(defect_dir, self.max_defects)

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    def read_meta(self, cache_root: Path, seq_no: int, *, view: Optional[str]) -> Optional[dict]:
        """
        读取指定序列的 cache.json 元数据；用于缓存刷新/补充逻辑。
        """
        base = self.cache_dir(cache_root, seq_no, view)
        meta_path = base / "cache.json"
        if not meta_path.exists():
            return None
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _ensure_cache_json(self, cache_root: Path, seq_no: int, *, view: Optional[str]) -> None:
        base = self.cache_dir(cache_root, seq_no, view)
        meta_path = base / "cache.json"
        if meta_path.exists():
            try:
                existing = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = None
            if isinstance(existing, dict):
                tile_meta = existing.get("tile") or {}
                defect_meta = existing.get("defects") or {}
                existing_level = int(tile_meta.get("max_level") or 0)
                existing_expand = int(defect_meta.get("expand") or 0)
                if (
                    existing_level == self.max_level()
                    and existing_expand == self.defect_expand
                    and str(existing.get("view") or "") == str(view or self.view_name)
                ):
                    return
        base.mkdir(parents=True, exist_ok=True)
        payload = {
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "view": (view or self.view_name),
            "tile": {
                "tile_size": self.tile_size,
                "max_level": self.max_level(),
                "format": "JPEG",
            },
            "defects": {
                "format": "JPEG",
                "expand": self.defect_expand,
                "enabled": bool(self.enabled),
            },
        }
        try:
            self._atomic_write(meta_path, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
            logger.info("disk-cache meta %s 完成", meta_path)
        except OSError:
            return

    def _atomic_write(self, path: Path, payload: bytes) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        tmp = path.with_suffix(path.suffix + ".tmp")
        with self._lock:
            try:
                tmp.write_bytes(payload)
                tmp.replace(path)
            except OSError:
                try:
                    if tmp.exists():
                        tmp.unlink()
                except OSError:
                    pass

    @staticmethod
    def _enforce_limit(root: Path, max_items: int) -> None:
        if not root.exists():
            return
        try:
            files = [p for p in root.rglob("*.jpg") if p.is_file()]
        except OSError:
            return
        if len(files) <= max_items:
            return
        try:
            files.sort(key=lambda p: p.stat().st_mtime)
        except OSError:
            return
        for path in files[: max(0, len(files) - max_items)]:
            try:
                path.unlink()
            except OSError:
                continue
