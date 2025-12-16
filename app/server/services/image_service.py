from __future__ import annotations

import math
import logging
import threading
from pathlib import Path
from typing import List, Optional, Tuple
import json

from PIL import Image

from ..config.settings import ImageSettings, ServerSettings
from ..cache import DiskImageCache, TtlLruCache
from ..schemas import DefectRecord
from ..utils.image_ops import (
    Box,
    encode_image,
    expand_box,
    open_image_from_bytes,
    resize_image,
)
from .defect_service import DefectService
from .tile_prefetch import TilePrefetchManager, TileRequest

logger = logging.getLogger(__name__)


class ImageService:
    def __init__(self, settings: ServerSettings, defect_service: DefectService):
        self.settings = settings
        self.defect_service = defect_service
        image_settings = settings.images
        self.mode = image_settings.mode
        ttl_seconds = image_settings.cache_ttl_seconds
        self.frame_cache = TtlLruCache(
            max_items=image_settings.max_cached_frames,
            ttl_seconds=ttl_seconds,
        )
        tile_ttl_seconds = ttl_seconds
        if image_settings.tile_prefetch_enabled:
            tile_ttl_seconds = max(tile_ttl_seconds, int(image_settings.tile_prefetch_ttl_seconds))
        self.tile_cache = TtlLruCache(max_items=image_settings.max_cached_tiles, ttl_seconds=tile_ttl_seconds)
        self.mosaic_cache = TtlLruCache(
            max_items=image_settings.max_cached_mosaics,
            ttl_seconds=ttl_seconds,
        )
        self.defect_crop_cache = TtlLruCache(
            max_items=image_settings.max_cached_defect_crops,
            ttl_seconds=ttl_seconds,
        )

        self.disk_cache = DiskImageCache(
            enabled=image_settings.disk_cache_enabled,
            max_tiles=image_settings.disk_cache_max_tiles,
            max_defects=image_settings.disk_cache_max_defects,
            defect_expand=32,
            tile_size=image_settings.frame_height,
            frame_width=image_settings.frame_width,
            frame_height=image_settings.frame_height,
            view_name=image_settings.default_view,
        )
        self._disk_cache_stop = threading.Event()
        self._disk_cache_thread_started = False

        self._tile_prefetch_started = False
        self._tile_prefetch: Optional[TilePrefetchManager] = None
        if image_settings.tile_prefetch_enabled:
            self._tile_prefetch = TilePrefetchManager(
                service=self,
                workers=int(image_settings.tile_prefetch_workers),
                ttl_seconds=int(image_settings.tile_prefetch_ttl_seconds),
            )

    def start_background_workers(self) -> None:
        image_settings = self.settings.images
        self._start_tile_prefetch_threads()
        if not image_settings.disk_cache_enabled:
            return
        logger.info(
            "disk-cache enabled view=%s tile_size=%s max_level=%s max_tiles=%s max_defects=%s",
            image_settings.default_view,
            image_settings.frame_height,
            self.disk_cache.max_level(),
            image_settings.disk_cache_max_tiles,
            image_settings.disk_cache_max_defects,
        )
        logger.info(
            "disk-cache threads precache=%s levels=%s scan_interval=%ss cleanup_interval=%ss",
            image_settings.disk_cache_precache_enabled,
            image_settings.disk_cache_precache_levels,
            image_settings.disk_cache_scan_interval_seconds,
            image_settings.disk_cache_cleanup_interval_seconds,
        )
        self._start_disk_cache_threads()

    def stop_background_workers(self) -> None:
        if self._tile_prefetch is not None:
            self._tile_prefetch.stop()
            self._tile_prefetch_started = False
        if not self.settings.images.disk_cache_enabled:
            return
        self._disk_cache_stop.set()
        logger.info("disk-cache worker threads stop requested")

    # --------------------------------------------------------------------- #
    # Frame level helpers
    # --------------------------------------------------------------------- #
    def get_frame(
        self,
        surface: str,
        seq_no: int,
        image_index: int,
        *,
        view: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        fmt: str = "JPEG",
    ) -> bytes:
        image = self._load_frame(surface, seq_no, image_index, view=view)
        if width or height:
            image = resize_image(image, width=width, height=height)
        return encode_image(image, fmt=fmt)

    def get_surface_image_info(
        self,
        surface: str,
        seq_no: int,
        *,
        view: Optional[str] = None,
    ) -> Tuple[int, int, int]:
        """
        返回指定序列在某一表面的帧数量及单帧尺寸信息。

        :return: (frame_count, image_width, image_height)
        """
        view_dir = view or self.settings.images.default_view

        # 优先尝试读取 record.json 中的 imgNum（如果存在）。
        # small 实例下，record.json 目前仍保存在 2D 目录，因此需要优先从当前视图读取，
        # 如果没有再回退到 2D 目录。
        surface_root = self._surface_root(surface)
        candidate_views: list[str] = [view_dir]
        if view_dir.lower() != "2d":
            candidate_views.append("2D")

        frame_count: Optional[int] = None
        for candidate_view in candidate_views:
            record_dir = surface_root / str(seq_no) / candidate_view
            record_path = record_dir / "record.json"
            if not record_path.exists():
                continue
            try:
                payload = json.loads(record_path.read_text(encoding="utf-8"))
                raw = payload.get("imgNum") or payload.get("img_num")
                if isinstance(raw, int) and raw > 0:
                    frame_count = raw
                    break
            except Exception:
                frame_count = None

        # 回退：通过扫描帧文件获取数量
        if frame_count is None:
            try:
                frames = self._list_frame_paths(surface, seq_no, view_dir)
            except FileNotFoundError:
                raise
            frame_count = len(frames)

        # 单帧尺寸由配置文件给出（server.json / server_small.json）
        image_width = self.settings.images.frame_width
        image_height = self.settings.images.frame_height

        return frame_count, image_width, image_height

    def crop_defect(
        self,
        surface: str,
        defect_id: int,
        *,
        expand: int = 0,
        width: Optional[int] = None,
        height: Optional[int] = None,
        fmt: str = "JPEG",
    ) -> Tuple[bytes, DefectRecord]:
        cache_key = (surface, defect_id, expand, width, height, fmt)
        cached = self.defect_crop_cache.get(cache_key)
        if cached is not None:
            return cached

        defect = self.defect_service.find_defect_by_surface(surface, defect_id)
        if not defect or defect.image_index is None:
            raise FileNotFoundError(f"Defect {defect_id} not found on {surface}")

        if (
            fmt.upper() == "JPEG"
            and width is None
            and height is None
            and expand == self.disk_cache.defect_expand
        ):
            disk = self.disk_cache.read_defect(
                self._surface_root(surface),
                defect.seq_no,
                view=None,
                surface=surface,
                defect_id=defect_id,
            )
            if disk is not None:
                result = (disk, defect)
                self.defect_crop_cache.put(cache_key, result)
                return result

        image = self._load_frame(surface, defect.seq_no, defect.image_index)
        box = (defect.bbox_image.left, defect.bbox_image.top, defect.bbox_image.right, defect.bbox_image.bottom)
        box = expand_box(box, expand, image.width, image.height)
        cropped = image.crop(box)
        if width or height:
            cropped = resize_image(cropped, width=width, height=height)
        payload = encode_image(cropped, fmt=fmt)
        result = (payload, defect)
        if (
            fmt.upper() == "JPEG"
            and width is None
            and height is None
            and expand == self.disk_cache.defect_expand
        ):
            self.disk_cache.write_defect(
                self._surface_root(surface),
                defect.seq_no,
                view=None,
                surface=surface,
                defect_id=defect_id,
                payload=payload,
            )
        self.defect_crop_cache.put(cache_key, result)
        return result

    def crop_custom(
        self,
        surface: str,
        seq_no: int,
        image_index: int,
        *,
        x: int,
        y: int,
        w: int,
        h: int,
        expand: int = 0,
        width: Optional[int] = None,
        height: Optional[int] = None,
        fmt: str = "JPEG",
    ) -> bytes:
        image = self._load_frame(surface, seq_no, image_index)
        box: Box = (x, y, x + w, y + h)
        box = expand_box(box, expand, image.width, image.height)
        cropped = image.crop(box)
        if width or height:
            cropped = resize_image(cropped, width=width, height=height)
        return encode_image(cropped, fmt=fmt)

    # --------------------------------------------------------------------- #
    # Mosaic helpers
    # --------------------------------------------------------------------- #
    def get_mosaic(
        self,
        surface: str,
        seq_no: int,
        *,
        view: Optional[str] = None,
        limit: Optional[int] = None,
        skip: int = 0,
        stride: int = 1,
        width: Optional[int] = None,
        height: Optional[int] = None,
        fmt: str = "JPEG",
    ) -> bytes:
        mosaic = self._build_mosaic(surface, seq_no, view=view, limit=limit, skip=skip, stride=stride)
        if width or height:
            mosaic = resize_image(mosaic, width=width, height=height)
        return encode_image(mosaic, fmt=fmt)

    def get_tile(
        self,
        surface: str,
        seq_no: int,
        *,
        view: Optional[str] = None,
        level: int = 0,
        tile_x: int,
        tile_y: int,
        orientation: str = "vertical",
        fmt: str = "JPEG",
        viewer_id: Optional[str] = None,
    ) -> bytes:
        return self._get_tile_impl(
            surface=surface,
            seq_no=seq_no,
            view=view,
            level=level,
            tile_x=tile_x,
            tile_y=tile_y,
            orientation=orientation,
            fmt=fmt,
            trigger_prefetch=True,
            viewer_id=(viewer_id or ""),
        )

    def _get_tile_impl(
        self,
        surface: str,
        seq_no: int,
        *,
        view: Optional[str],
        level: int,
        tile_x: int,
        tile_y: int,
        orientation: str,
        fmt: str,
        trigger_prefetch: bool,
        viewer_id: str,
    ) -> bytes:
        view_dir = view or self.settings.images.default_view
        tile_size = self.settings.images.frame_height
        orientation = (orientation or "vertical").lower()
        if orientation not in {"horizontal", "vertical"}:
            raise ValueError(f"Unsupported orientation '{orientation}'")
        orientation = "vertical"
        if level < 0:
            raise ValueError("Unsupported level (must be >= 0)")
        max_level = self.disk_cache.max_level()
        if level > max_level:
            raise ValueError(f"Unsupported level {level} (max {max_level})")

        cache_key = (surface, seq_no, view_dir, orientation, level, tile_x, tile_y, fmt)
        data: Optional[bytes] = None
        if fmt.upper() == "JPEG":
            disk = self.disk_cache.read_tile(
                self._surface_root(surface),
                seq_no,
                view=view_dir,
                level=level,
                orientation=orientation,
                tile_x=tile_x,
                tile_y=tile_y,
            )
            if disk is not None:
                self.tile_cache.put(cache_key, disk)
                data = disk
        if data is None:
            cached = self.tile_cache.get(cache_key)
            if cached is not None:
                data = cached

        if data is None:
            # 基于原始帧列表按需拼接当前瓦片所需区域，而不是预先构建整幅马赛克。
            frames = self._list_frame_paths(surface, seq_no, view_dir)
            if not frames:
                raise FileNotFoundError(f"No frames found for {surface} seq={seq_no}")

            # 假设所有帧尺寸一致，读取首帧确定尺寸
            first_img = self._load_frame_from_path(frames[0])
            frame_w, frame_h = first_img.width, first_img.height

            if orientation == "horizontal":
                stripe_w = frame_h
                stripe_h = frame_w
                mosaic_width = stripe_w * len(frames)
                mosaic_height = stripe_h
            else:
                stripe_w = frame_w
                stripe_h = frame_h
                mosaic_width = stripe_w
                mosaic_height = stripe_h * len(frames)

            virtual_tile_size = tile_size * (2**level)
            left0 = tile_x * virtual_tile_size
            top0 = tile_y * virtual_tile_size

            if left0 >= mosaic_width or top0 >= mosaic_height:
                raise FileNotFoundError(f"Tile ({tile_x}, {tile_y}) out of bounds for {surface} seq={seq_no}")

            right0 = min(left0 + virtual_tile_size, mosaic_width)
            bottom0 = min(top0 + virtual_tile_size, mosaic_height)

            width0 = right0 - left0
            height0 = bottom0 - top0

            # 在 level=0 坐标系下构建瓦片，再按 level 缩放
            base_tile = Image.new("RGB", (width0, height0))

            if orientation == "horizontal":
                first_idx = left0 // stripe_w
                last_idx = min(len(frames) - 1, (right0 - 1) // stripe_w)

                for idx in range(first_idx, last_idx + 1):
                    stripe_path = frames[idx]
                    src_img = self._load_frame_from_path(stripe_path)
                    rot = src_img.transpose(Image.Transpose.ROTATE_90)

                    stripe_x0 = idx * stripe_w
                    stripe_x1 = stripe_x0 + stripe_w

                    xg0 = max(left0, stripe_x0)
                    xg1 = min(right0, stripe_x1)
                    if xg1 <= xg0:
                        continue

                    # 在单帧（旋转后）坐标系中的裁剪区域
                    x_local0 = xg0 - stripe_x0
                    x_local1 = xg1 - stripe_x0

                    # 垂直方向在所有帧上对齐
                    y_local0 = top0
                    y_local1 = bottom0

                    crop_box: Box = (int(x_local0), int(y_local0), int(x_local1), int(y_local1))
                    stripe_crop = rot.crop(crop_box)

                    # 粘贴到当前瓦片的相对位置
                    dest_x = xg0 - left0
                    base_tile.paste(stripe_crop, (int(dest_x), 0))
            else:
                first_idx = top0 // stripe_h
                last_idx = min(len(frames) - 1, (bottom0 - 1) // stripe_h)

                for idx in range(first_idx, last_idx + 1):
                    stripe_path = frames[idx]
                    src_img = self._load_frame_from_path(stripe_path)

                    stripe_y0 = idx * stripe_h
                    stripe_y1 = stripe_y0 + stripe_h

                    yg0 = max(top0, stripe_y0)
                    yg1 = min(bottom0, stripe_y1)
                    if yg1 <= yg0:
                        continue

                    x_local0 = left0
                    x_local1 = right0
                    y_local0 = yg0 - stripe_y0
                    y_local1 = yg1 - stripe_y0

                    crop_box = (int(x_local0), int(y_local0), int(x_local1), int(y_local1))
                    stripe_crop = src_img.crop(crop_box)

                    dest_y = yg0 - top0
                    base_tile.paste(stripe_crop, (0, int(dest_y)))

            # 对 level>0 进行缩放，得到最终瓦片图像尺寸
            if level > 0:
                scale = 1 / (2**level)
                target_w = max(1, int(round(width0 * scale)))
                target_h = max(1, int(round(height0 * scale)))
                tile_img = base_tile.resize((target_w, target_h), Image.Resampling.BILINEAR)
            else:
                tile_img = base_tile

            data = encode_image(tile_img, fmt=fmt)
            self.tile_cache.put(cache_key, data)
            if fmt.upper() == "JPEG":
                self.disk_cache.write_tile(
                    self._surface_root(surface),
                    seq_no,
                    view=view_dir,
                    level=level,
                    orientation=orientation,
                    tile_x=tile_x,
                    tile_y=tile_y,
                    payload=data,
                )

        if trigger_prefetch:
            self._schedule_tile_prefetch(
                viewer_id=viewer_id,
                surface=surface,
                seq_no=seq_no,
                view=view_dir,
                level=level,
                tile_x=tile_x,
                tile_y=tile_y,
            )
        return data

    def _start_tile_prefetch_threads(self) -> None:
        if self._tile_prefetch_started:
            return
        if self._tile_prefetch is None:
            return
        self._tile_prefetch.start()
        self._tile_prefetch_started = True

    def _schedule_tile_prefetch(
        self,
        *,
        viewer_id: str,
        surface: str,
        seq_no: int,
        view: str,
        level: int,
        tile_x: int,
        tile_y: int,
    ) -> None:
        manager = self._tile_prefetch
        if manager is None:
            return
        if not self._tile_prefetch_started:
            manager.start()
            self._tile_prefetch_started = True

        max_level = self.disk_cache.max_level()
        settings = self.settings.images
        viewer_id = (viewer_id or "").strip()
        if viewer_id and settings.tile_prefetch_clear_pending_on_seq_change:
            manager.notify_seq_request(
                viewer_id=viewer_id,
                seq_no=seq_no,
                clear_pending=True,
            )

        if not viewer_id:
            return

        # Same-level adjacent tiles (configurable, default 1).
        neighbor_count = int(settings.tile_prefetch_adjacent_tile_count)
        if neighbor_count > 0:
            offsets_by_name: dict[str, tuple[int, int]] = {
                "right": (1, 0),
                "left": (-1, 0),
                "down": (0, 1),
                "up": (0, -1),
                "down_right": (1, 1),
                "down_left": (-1, 1),
                "up_right": (1, -1),
                "up_left": (-1, -1),
            }
            picked = 0
            for name in settings.tile_prefetch_adjacent_tile_order:
                dx, dy = offsets_by_name.get(str(name).lower(), (0, 0))
                if dx == 0 and dy == 0:
                    continue
                nx = tile_x + dx
                ny = tile_y + dy
                if nx < 0 or ny < 0:
                    continue
                manager.enqueue_tile(
                    TileRequest(
                        viewer_id=viewer_id,
                        surface=surface,
                        seq_no=seq_no,
                        view=view,
                        level=level,
                        tile_x=nx,
                        tile_y=ny,
                    ),
                    priority=1,
                )
                picked += 1
                if picked >= neighbor_count:
                    break

        # Cross-level prefetch (optional).
        if settings.tile_prefetch_cross_level_enabled:
            if level > 0:
                child_level = level - 1
                base_x = tile_x * 2
                base_y = tile_y * 2
                for dx in (0, 1):
                    for dy in (0, 1):
                        manager.enqueue_tile(
                            TileRequest(
                                viewer_id=viewer_id,
                                surface=surface,
                                seq_no=seq_no,
                                view=view,
                                level=child_level,
                                tile_x=base_x + dx,
                                tile_y=base_y + dy,
                            ),
                            priority=1,
                        )
            if level < max_level:
                manager.enqueue_tile(
                    TileRequest(
                        viewer_id=viewer_id,
                        surface=surface,
                        seq_no=seq_no,
                        view=view,
                        level=level + 1,
                        tile_x=tile_x // 2,
                        tile_y=tile_y // 2,
                    ),
                    priority=1,
                )

        # Adjacent seq_no warmup (optional).
        if settings.tile_prefetch_adjacent_seq_enabled:
            warm_levels: list[tuple[int, int]] = []
            if max_level >= 4 and settings.tile_prefetch_adjacent_seq_level4_count > 0:
                warm_levels.append((4, int(settings.tile_prefetch_adjacent_seq_level4_count)))
            if max_level >= 3 and settings.tile_prefetch_adjacent_seq_level3_count > 0:
                warm_levels.append((3, int(settings.tile_prefetch_adjacent_seq_level3_count)))
            if warm_levels:
                manager.maybe_enqueue_adjacent_warm(
                    viewer_id=viewer_id,
                    surface=surface,
                    seq_no=seq_no,
                    view=view,
                    warm_levels=warm_levels,
                    priority=2,
                )

    def _first_tile_coords(
        self,
        *,
        surface: str,
        seq_no: int,
        view: str,
        level: int,
        count: int,
    ) -> list[tuple[int, int]]:
        tile_size = self.settings.images.frame_height
        frames = self._list_frame_paths(surface, seq_no, view)
        if not frames:
            return []
        first_img = self._load_frame_from_path(frames[0])
        mosaic_width = first_img.width
        mosaic_height = first_img.height * len(frames)

        virtual_tile_size = tile_size * (2**level)
        tiles_x = max(1, int(math.ceil(mosaic_width / virtual_tile_size)))
        tiles_y = max(1, int(math.ceil(mosaic_height / virtual_tile_size)))

        coords: list[tuple[int, int]] = []
        for y in range(tiles_y):
            for x in range(tiles_x):
                coords.append((x, y))
                if len(coords) >= count:
                    return coords
        return coords

    # --------------------------------------------------------------------- #
    # Disk cache workers
    # --------------------------------------------------------------------- #
    def _start_disk_cache_threads(self) -> None:
        if self._disk_cache_thread_started:
            return
        self._disk_cache_thread_started = True
        logger.info("disk-cache worker threads 启动")
        if self.settings.images.disk_cache_precache_enabled:
            threading.Thread(target=self._disk_cache_precache_loop, daemon=True).start()
            logger.info("disk-cache precache thread 启动")
        threading.Thread(target=self._disk_cache_cleanup_loop, daemon=True).start()
        logger.info("disk-cache cleanup thread 启动")

    def _disk_cache_precache_loop(self) -> None:
        settings = self.settings.images
        scan_interval = settings.disk_cache_scan_interval_seconds
        precache_levels = settings.disk_cache_precache_levels
        last_seq_by_surface: dict[str, int] = {"top": 0, "bottom": 0}

        while not self._disk_cache_stop.is_set():
            for surface in ("top", "bottom"):
                root = self._surface_root(surface)
                max_seq = self._find_max_seq(root)
                current = last_seq_by_surface.get(surface, 0)
                if max_seq is None or max_seq <= current:
                    continue
                for seq in range(current + 1, max_seq + 1):
                    try:
                        self._precache_seq(surface, seq, precache_levels=precache_levels)
                        last_seq_by_surface[surface] = seq
                    except Exception:
                        break
            self._disk_cache_stop.wait(scan_interval)

    def _disk_cache_cleanup_loop(self) -> None:
        settings = self.settings.images
        interval = settings.disk_cache_cleanup_interval_seconds
        view_dir = self.settings.images.default_view

        while not self._disk_cache_stop.is_set():
            for surface in ("top", "bottom"):
                root = self._surface_root(surface)
                for seq in self._list_seq_dirs(root)[-20:]:
                    try:
                        self.disk_cache.cleanup_seq(root, seq, view=view_dir)
                    except Exception:
                        continue
            self._disk_cache_stop.wait(interval)

    def _precache_seq(self, surface: str, seq_no: int, *, precache_levels: int) -> None:
        view_dir = self.settings.images.default_view
        max_level = self.disk_cache.max_level()
        levels = max(1, int(precache_levels))
        level_start = max(0, max_level - levels + 1)

        tile_size = self.settings.images.frame_height

        for level in range(max_level, level_start - 1, -1):
            virtual_tile_size = tile_size * (2**level)
            frames = self._list_frame_paths(surface, seq_no, view_dir)
            if not frames:
                return
            first_img = self._load_frame_from_path(frames[0])
            mosaic_width = first_img.width
            mosaic_height = first_img.height * len(frames)

            tiles_x = max(1, int(math.ceil(mosaic_width / virtual_tile_size)))
            tiles_y = max(1, int(math.ceil(mosaic_height / virtual_tile_size)))

            for tile_y in range(tiles_y):
                for tile_x in range(tiles_x):
                    self.get_tile(
                        surface=surface,
                        seq_no=seq_no,
                        view=view_dir,
                        level=level,
                        tile_x=tile_x,
                        tile_y=tile_y,
                        orientation="vertical",
                        fmt="JPEG",
                    )
        logger.info("disk-cache precache %s/%s/%s 完成", surface, seq_no, view_dir)

    @staticmethod
    def _list_seq_dirs(root: Path) -> list[int]:
        if not root.exists():
            return []
        seqs: list[int] = []
        try:
            for entry in root.iterdir():
                if not entry.is_dir():
                    continue
                try:
                    seqs.append(int(entry.name))
                except ValueError:
                    continue
        except OSError:
            return []
        seqs.sort()
        return seqs

    def _find_max_seq(self, root: Path) -> Optional[int]:
        seqs = self._list_seq_dirs(root)
        return seqs[-1] if seqs else None

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #
    def _load_frame(self, surface: str, seq_no: int, image_index: int, view: Optional[str] = None) -> Image.Image:
        view_dir = view or self.settings.images.default_view
        ext = self.settings.images.file_extension
        root = self._surface_root(surface)
        path = root / str(seq_no) / view_dir / f"{image_index}.{ext}"
        key = ("frame", path.as_posix())
        cached = self.frame_cache.get(key)
        if cached is not None:
            return open_image_from_bytes(cached, mode=self.mode)
        if not path.exists():
            raise FileNotFoundError(path)
        data = path.read_bytes()
        self.frame_cache.put(key, data)
        return open_image_from_bytes(data, mode=self.mode)

    def _surface_root(self, surface: str) -> Path:
        surface = surface.lower()
        if surface == "top":
            return self.settings.images.top_root
        if surface == "bottom":
            return self.settings.images.bottom_root
        raise ValueError(f"Unknown surface '{surface}'")

    def _list_frame_paths(self, surface: str, seq_no: int, view: str) -> List[Path]:
        root = self._surface_root(surface)
        folder = root / str(seq_no) / view
        if not folder.exists():
            raise FileNotFoundError(folder)
        ext = self.settings.images.file_extension
        files = list(folder.glob(f"*.{ext}"))
        files.sort(key=self._frame_sort_key)
        return files

    @staticmethod
    def _frame_sort_key(path: Path):
        try:
            return int(path.stem)
        except ValueError:
            return path.stem

    def _build_mosaic(
        self,
        surface: str,
        seq_no: int,
        *,
        view: Optional[str],
        limit: Optional[int],
        skip: int,
        stride: int,
    ) -> Image.Image:
        key = (surface, seq_no, view or self.settings.images.default_view, limit, skip, stride)
        cached = self.mosaic_cache.get(key)
        if cached is not None:
            return cached.copy()
        view_dir = view or self.settings.images.default_view
        frames = self._list_frame_paths(surface, seq_no, view_dir)
        if skip:
            frames = frames[skip:]
        if stride > 1:
            frames = frames[::stride]
        if limit:
            frames = frames[:limit]
        if not frames:
            raise FileNotFoundError(f"No frames found for {surface} seq={seq_no}")
        # 构建横向长带拼接图：将每帧逆时针旋转 90° 后按 X 方向依次拼接
        images = [self._load_frame_from_path(path) for path in frames]
        # 先对每一帧做逆时针 90° 旋转，使钢板长度方向沿水平方向展开
        rotated_images = [img.transpose(Image.Transpose.ROTATE_90) for img in images]
        width = sum(img.width for img in rotated_images)
        height = max(img.height for img in rotated_images)
        mosaic = Image.new("RGB", (width, height))
        current_x = 0
        for img in rotated_images:
            mosaic.paste(img, (current_x, 0))
            current_x += img.width
        self.mosaic_cache.put(key, mosaic.copy())
        return mosaic

    def _load_frame_from_path(self, path: Path) -> Image.Image:
        key = ("frame", path.as_posix())
        cached = self.frame_cache.get(key)
        if cached is not None:
            return open_image_from_bytes(cached, mode=self.mode)
        data = path.read_bytes()
        self.frame_cache.put(key, data)
        return open_image_from_bytes(data, mode=self.mode)
