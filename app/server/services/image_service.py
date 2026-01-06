from __future__ import annotations

import math
import logging
import threading
from pathlib import Path
from typing import List, Optional, Tuple
import json

from PIL import Image, ImageDraw, ImageFont

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
prefetch_logger = logging.getLogger("uvicorn.error")


class ImageService:
    def __init__(self, settings: ServerSettings, defect_service: DefectService):
        self.settings = settings
        self.defect_service = defect_service
        self.test_mode = bool(getattr(settings, "test_mode", False))
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
            read_only=self.test_mode,
            flat_layout=False,
            max_tiles=image_settings.disk_cache_max_tiles,
            max_defects=image_settings.disk_cache_max_defects,
            # 缺陷缓存最大裁剪保留来自配置
            defect_expand=int(getattr(image_settings, "defect_cache_expand", 100) or 100),
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
                log_enabled=bool(image_settings.tile_prefetch_log_enabled),
                log_detail=str(image_settings.tile_prefetch_log_detail),
            )

        # 缓存错误图像的编码结果，避免重复绘制与编码
        self._error_image_cache: dict[tuple[str, str], bytes] = {}

    # ------------------------------------------------------------------ #
    # Defect warmup helpers
    # ------------------------------------------------------------------ #
    def warmup_defects_for_seq(self, seq_no: int, surface: Optional[str] = None) -> None:
        """
        预热指定钢板的全部缺陷小图：
        - 优先命中内存缓存 / 磁盘缓存；
        - 若缺失，再从原图裁剪并写入磁盘缓存，
          以便后续前端请求时尽量不再经过 Pillow/OpenCV 的在线裁剪。
        """
        images = self.settings.images
        if not getattr(images, "disk_cache_enabled", False) or not getattr(images, "defect_cache_enabled", True):
            return
        try:
            # surface=None 时同时预热 top/bottom，两侧的缺陷记录都会返回
            resp = self.defect_service.defects_by_seq(seq_no, surface=surface)
        except Exception:
            logger.exception("warmup defects: load defect list failed seq=%s surface=%s", seq_no, surface)
            return

        default_expand = self.disk_cache.defect_expand
        for item in resp.items:
            try:
                # 仅预热标准 JPEG + 默认扩展像素的小图，便于前端直接复用。
                self.crop_defect(
                    surface=item.surface,
                    defect_id=item.defect_id,
                    expand=default_expand,
                    width=None,
                    height=None,
                    fmt="JPEG",
                )
            except FileNotFoundError:
                # 对单个缺陷缺图容忍，继续预热其他记录
                continue
            except Exception:
                logger.exception(
                    "warmup defects: crop failed seq=%s surface=%s defect_id=%s",
                    seq_no,
                    item.surface,
                    item.defect_id,
                )

    def start_background_workers(self) -> None:
        image_settings = self.settings.images
        self._start_tile_prefetch_threads()
        if not image_settings.disk_cache_enabled or self.disk_cache.read_only:
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
        seq_no_fs = self._resolve_seq_no_for_fs(surface_root, seq_no)
        candidate_views: list[str] = [view_dir]
        if view_dir.lower() != "2d":
            candidate_views.append("2D")

        frame_count: Optional[int] = None
        for candidate_view in candidate_views:
            record_dirs = [surface_root / str(seq_no_fs) / candidate_view]
            for record_dir in record_dirs:
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
            if frame_count is not None:
                break

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
        expand: Optional[int] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        fmt: str = "JPEG",
    ) -> Tuple[bytes, DefectRecord]:
        # 若未显式指定扩展像素，则使用配置中的缺陷缓存扩展像素
        if expand is None:
            expand = self.disk_cache.defect_expand

        cache_key = (surface, defect_id, expand, width, height, fmt)
        cached = self.defect_crop_cache.get(cache_key)
        if cached is not None:
            return cached

        defect = self.defect_service.find_defect_by_surface(surface, defect_id)
        if not defect or defect.image_index is None:
            raise FileNotFoundError(f"Defect {defect_id} not found on {surface}")

        # 坐标体系说明：
        # - leftInSrcImg/... 一列表示在“原始源图像”上的像素坐标（单帧）——这是可信坐标。
        # - leftInImg/... 已弃用，不再直接用于裁剪。
        # 这里优先使用 bbox_source（来源于 leftInSrcImg 等），
        # 在 SMALL 实例下再根据 pixel_scale 做缩放，使之适配当前实例实际帧尺寸。
        base_bbox = defect.bbox_source or defect.bbox_image
        if base_bbox is None:
            raise FileNotFoundError(f"Defect {defect_id} bbox not available on {surface}")

        # 根据当前实例的 pixel_scale（例如 SMALL 模式下为 0.5）缩放坐标
        try:
            scale = float(getattr(self.settings.images, "pixel_scale", 1.0))
        except Exception:
            scale = 1.0
        if scale <= 0:
            scale = 1.0

        # 计算用于磁盘缓存文件名的“源坐标 + 扩展配置”键，确保同一缺陷在同一配置下命中。
        width_src = max(0, base_bbox.right - base_bbox.left)
        height_src = max(0, base_bbox.bottom - base_bbox.top)
        surface_code = "t" if surface.lower() == "top" else "b"
        # 磁盘文件名主体：{seq_no}_{t/b}_{defect_id}_{leftInSrcImg}_{topInSrcImg}_{宽度}_{高度}_{defect_cache_expand}
        disk_defect_id = (
            f"{defect.seq_no}_{surface_code}_{defect.defect_id}_"
            f"{base_bbox.left}_{base_bbox.top}_{width_src}_{height_src}_{self.disk_cache.defect_expand}"
        )

        if (
            fmt.upper() == "JPEG"
            and width is None
            and height is None
            and expand == self.disk_cache.defect_expand
        ):
            surface_root = self._surface_root(surface)
            cache_root = self._cache_root(surface)
            seq_no_fs = self._resolve_seq_no_for_fs(surface_root, defect.seq_no)
            disk = self.disk_cache.read_defect(
                cache_root,
                seq_no_fs,
                view=None,
                surface=surface,
                defect_id=disk_defect_id,
            )
            if disk is not None:
                result = (disk, defect)
                self.defect_crop_cache.put(cache_key, result)
                return result

        try:
            image = self._load_frame(surface, defect.seq_no, defect.image_index)
        except FileNotFoundError:
            # 原始帧不存在，返回默认错误图像（缓存后的二进制）
            payload = self._error_image_bytes("原图丢失\nDEFECT IMAGE MISSING", fmt=fmt)
            result = (payload, defect)
            self.defect_crop_cache.put(cache_key, result)
            return result

        # 如果源坐标完全落在图像范围外，则直接返回错误图像
        if (
            base_bbox.right <= 0
            or base_bbox.bottom <= 0
            or base_bbox.left >= image.width
            or base_bbox.top >= image.height
        ):
            payload = self._error_image_bytes("坐标越界\nBBOX OUT OF RANGE", fmt=fmt)
            result = (payload, defect)
            self.defect_crop_cache.put(cache_key, result)
            return result
        if scale != 1.0:
            left = int(round(base_bbox.left * scale))
            top = int(round(base_bbox.top * scale))
            right = int(round(base_bbox.right * scale))
            bottom = int(round(base_bbox.bottom * scale))
        else:
            left = base_bbox.left
            top = base_bbox.top
            right = base_bbox.right
            bottom = base_bbox.bottom

        box = (left, top, right, bottom)
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
                self._cache_root(surface),
                self._resolve_seq_no_for_fs(self._surface_root(surface), defect.seq_no),
                view=None,
                surface=surface,
                defect_id=disk_defect_id,
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
        surface_root = self._surface_root(surface)
        cache_root = self._cache_root(surface)
        seq_no_fs = self._resolve_seq_no_for_fs(surface_root, seq_no)
        orientation = (orientation or "vertical").lower()
        if orientation not in {"horizontal", "vertical"}:
            raise ValueError(f"Unsupported orientation '{orientation}'")
        if level < 0:
            raise ValueError("Unsupported level (must be >= 0)")
        max_level = self.disk_cache.max_level()
        if level > max_level:
            raise ValueError(f"Unsupported level {level} (max {max_level})")

        cache_key = (surface, seq_no, view_dir, orientation, level, tile_x, tile_y, fmt)
        data: Optional[bytes] = None
        if fmt.upper() == "JPEG":
            disk = self.disk_cache.read_tile(
                cache_root,
                seq_no_fs,
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
                if self.test_mode:
                    tile_img = Image.new("RGB", (tile_size, tile_size))
                    data = encode_image(tile_img, fmt=fmt)
                    self.tile_cache.put(cache_key, data)
                    return data
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
                if self.test_mode:
                    tile_img = Image.new("RGB", (tile_size, tile_size))
                    data = encode_image(tile_img, fmt=fmt)
                    self.tile_cache.put(cache_key, data)
                    return data
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
                    cache_root,
                    seq_no_fs,
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
                seq_no=seq_no_fs,
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

        scheduled: list[tuple[int, int, int]] = []
        seq_warm: list[tuple[int, int, int]] = []

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
                scheduled.append((level, nx, ny))
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
                        scheduled.append((child_level, base_x + dx, base_y + dy))
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
                scheduled.append((level + 1, tile_x // 2, tile_y // 2))

        # Adjacent seq_no warmup (optional).
        if settings.tile_prefetch_adjacent_seq_enabled:
            warm_levels: list[tuple[int, int]] = []
            if max_level >= 4 and settings.tile_prefetch_adjacent_seq_level4_count > 0:
                warm_levels.append((4, int(settings.tile_prefetch_adjacent_seq_level4_count)))
            if max_level >= 3 and settings.tile_prefetch_adjacent_seq_level3_count > 0:
                warm_levels.append((3, int(settings.tile_prefetch_adjacent_seq_level3_count)))
            if warm_levels:
                for neighbor in (seq_no - 1, seq_no + 1):
                    if neighbor >= 0:
                        for lvl, cnt in warm_levels:
                            seq_warm.append((neighbor, lvl, cnt))
                manager.maybe_enqueue_adjacent_warm(
                    viewer_id=viewer_id,
                    surface=surface,
                    seq_no=seq_no,
                    view=view,
                    warm_levels=warm_levels,
                    priority=2,
                )

        if settings.tile_prefetch_log_enabled and settings.tile_prefetch_log_detail == "summary":
            prefetch_logger.info(
                "tile-prefetch warmup viewer=%s %s seq=%s view=%s req_level=%s x=%s y=%s tiles=%s seq_warm=%s",
                viewer_id,
                surface,
                seq_no,
                view,
                level,
                tile_x,
                tile_y,
                scheduled,
                seq_warm,
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
            # 先根据 cache.json 与当前配置比对，补充/刷新已有缓存
            try:
                self._refresh_disk_cache_meta(precache_levels=precache_levels)
            except Exception:
                logger.exception("disk-cache meta refresh 失败")

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
                root = self._cache_root(surface)
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

    def _refresh_disk_cache_meta(self, *, precache_levels: int) -> None:
        """
        根据 cache.json 与当前服务配置比对，决定是否对已有钢板序列进行补充缓存。
        典型场景：配置中的最大层级 / 扩展像素调整后，对历史钢板进行补齐。
        """
        view_dir = self.settings.images.default_view
        current_max_level = self.disk_cache.max_level()
        for surface in ("top", "bottom"):
            cache_root = self._cache_root(surface)
            # 仅针对最近若干序列，避免一次性全量扫描
            for seq in self._list_seq_dirs(cache_root)[-50:]:
                meta = self.disk_cache.read_meta(cache_root, seq, view=view_dir)
                if not meta:
                    continue
                meta_tile = (meta.get("tile") or {})
                meta_defects = (meta.get("defects") or {})
                meta_max_level = int(meta_tile.get("max_level") or 0)
                meta_expand = int(meta_defects.get("expand") or 0)
                # 如果当前配置支持更多层级或更大的缺陷扩展，则触发补充缓存
                needs_precache = False
                if current_max_level > meta_max_level:
                    needs_precache = True
                if self.disk_cache.defect_expand != meta_expand:
                    needs_precache = True
                if not needs_precache:
                    continue
                try:
                    self._precache_seq(surface, seq, precache_levels=precache_levels)
                except Exception:
                    logger.exception("disk-cache refresh 失败 surface=%s seq=%s", surface, seq)

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
        seq_no_fs = self._resolve_seq_no_for_fs(root, seq_no)
        path = self._resolve_frame_path(root, seq_no_fs, view_dir, image_index, ext)
        key = ("frame", path.as_posix())
        cached = self.frame_cache.get(key)
        if cached is not None:
            return open_image_from_bytes(cached, mode=self.mode)
        if not path.exists():
            if self.test_mode:
                return self._black_frame()
            raise FileNotFoundError(path)
        data = path.read_bytes()
        self.frame_cache.put(key, data)
        return open_image_from_bytes(data, mode=self.mode)

    def _black_frame(self) -> Image.Image:
        width = int(getattr(self.settings.images, "frame_width", 1024) or 1024)
        height = int(getattr(self.settings.images, "frame_height", 1024) or 1024)
        mode = self.mode or "RGB"
        return Image.new(mode, (width, height), 0)

    def _error_image(self, message: str = "ERROR", *, width: int = 256, height: int = 256) -> Image.Image:
        """
        默认错误图像：用于原图缺失或裁剪范围完全越界时的占位。

        设计：深色背景 + 红色边框 + 居中红色错误文案（支持简单多行）。
        """
        mode = self.mode or "RGB"
        try:
            image = Image.new(mode, (width, height), (20, 20, 20))
        except Exception:
            image = Image.new("RGB", (width, height), (20, 20, 20))
        draw = ImageDraw.Draw(image)

        # 红色边框
        border_color = (220, 20, 60)
        for offset in (0, 1):
            draw.rectangle(
                [offset, offset, width - 1 - offset, height - 1 - offset],
                outline=border_color,
                width=1,
            )

        # 文本：支持简单多行，居中绘制
        # 优先尝试加载系统中的中文字体，这样错误信息里的中文不会变成方块。
        try:
            font: Optional[ImageFont.ImageFont] = None
            # Windows 常见中文字体路径
            font_candidates = [
                Path("C:/Windows/Fonts/msyh.ttc"),
                Path("C:/Windows/Fonts/simhei.ttf"),
                Path("C:/Windows/Fonts/simsun.ttc"),
            ]
            for candidate in font_candidates:
                if candidate.exists():
                    font = ImageFont.truetype(str(candidate), 16)
                    break
            if font is None:
                font = ImageFont.load_default()
        except Exception:
            font = None  # Pillow 会用内置字体

        lines = str(message or "ERROR").splitlines() or ["ERROR"]
        line_heights: list[int] = []
        line_widths: list[int] = []

        def _measure(line: str) -> tuple[int, int]:
            # Pillow 版本兼容：优先用 textbbox，其次 font.getsize，最后估算
            if hasattr(draw, "textbbox"):
                bbox = draw.textbbox((0, 0), line, font=font)
                return max(1, bbox[2] - bbox[0]), max(1, bbox[3] - bbox[1])
            if font is not None and hasattr(font, "getsize"):
                w, h = font.getsize(line)
                return max(1, w), max(1, h)
            return max(1, len(line) * 8), 12

        for line in lines:
            w, h = _measure(line)
            line_widths.append(w)
            line_heights.append(h)
        total_height = sum(line_heights) + max(0, (len(lines) - 1) * 4)

        current_y = (height - total_height) // 2
        for idx, line in enumerate(lines):
            w = line_widths[idx]
            h = line_heights[idx]
            x = (width - w) // 2
            draw.text((x, current_y), line, fill=border_color, font=font)
            current_y += h + 4

        return image

    def _error_image_bytes(self, message: str, fmt: str = "JPEG", *, width: int = 256, height: int = 256) -> bytes:
        """
        获取带有给定错误消息的占位图二进制数据（带简单内存缓存）。
        """
        key = (str(message or "ERROR"), fmt.upper())
        cached = self._error_image_cache.get(key)
        if cached is not None:
            return cached
        image = self._error_image(message, width=width, height=height)
        payload = encode_image(image, fmt=fmt)
        self._error_image_cache[key] = payload
        return payload

    @staticmethod
    def _resolve_frame_path(root: Path, seq_no: int, view_dir: str, image_index: int, ext: str) -> Path:
        candidate = root / str(seq_no) / view_dir / f"{image_index}.{ext}"
        return candidate

    def _resolve_seq_no_for_fs(self, root: Path, seq_no: int) -> int:
        """
        Resolve the on-disk seq directory.

        Normal layout: {root}/{seq_no}/{view}/{index}.jpg

        In test mode: if {root}/{seq_no} is missing, fallback to {root}/1
        (behaves like "copied from 1", without writing anything).
        """
        seq_dir = root / str(seq_no)
        if seq_dir.exists():
            return seq_no
        if self.test_mode and (root / "1").exists():
            return 1
        return seq_no

    def _surface_root(self, surface: str) -> Path:
        surface = surface.lower()
        if surface == "top":
            return self.settings.images.top_root
        if surface == "bottom":
            return self.settings.images.bottom_root
        raise ValueError(f"Unknown surface '{surface}'")

    def _cache_root(self, surface: str) -> Path:
        surface = surface.lower()
        if surface == "top":
            return self.settings.images.disk_cache_top_root or self.settings.images.top_root
        if surface == "bottom":
            return self.settings.images.disk_cache_bottom_root or self.settings.images.bottom_root
        raise ValueError(f"Unknown surface '{surface}'")

    def _list_frame_paths(self, surface: str, seq_no: int, view: str) -> List[Path]:
        root = self._surface_root(surface)
        seq_no_fs = self._resolve_seq_no_for_fs(root, seq_no)
        folder = root / str(seq_no_fs) / view
        if not folder.exists():
            if self.test_mode:
                return []
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
            if self.test_mode:
                return Image.new("RGB", (self.settings.images.frame_width, self.settings.images.frame_height))
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
