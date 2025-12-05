from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image

from ..config.settings import ImageSettings, ServerSettings
from ..schemas import DefectRecord
from ..utils.cache import LRUCache
from ..utils.image_ops import (
    Box,
    encode_image,
    expand_box,
    open_image_from_bytes,
    resize_image,
)
from .defect_service import DefectService


class ImageService:
    def __init__(self, settings: ServerSettings, defect_service: DefectService):
        self.settings = settings
        self.defect_service = defect_service
        image_settings = settings.images
        self.mode = image_settings.mode
        self.frame_cache = LRUCache(max_items=image_settings.max_cached_frames)
        self.tile_cache = LRUCache(max_items=image_settings.max_cached_tiles)
        self.mosaic_cache = LRUCache(max_items=image_settings.max_cached_mosaics)

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
        frames = self._list_frame_paths(surface, seq_no, view_dir)
        if not frames:
            raise FileNotFoundError(f"No frames found for {surface} seq={seq_no}")
        first = self._load_frame_from_path(frames[0])
        return len(frames), first.width, first.height

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
        defect = self.defect_service.find_defect_by_surface(surface, defect_id)
        if not defect or defect.image_index is None:
            raise FileNotFoundError(f"Defect {defect_id} not found on {surface}")
        image = self._load_frame(surface, defect.seq_no, defect.image_index)
        box = (defect.bbox_image.left, defect.bbox_image.top, defect.bbox_image.right, defect.bbox_image.bottom)
        box = expand_box(box, expand, image.width, image.height)
        cropped = image.crop(box)
        if width or height:
            cropped = resize_image(cropped, width=width, height=height)
        return encode_image(cropped, fmt=fmt), defect

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
        tile_size: int = 512,
        fmt: str = "JPEG",
    ) -> bytes:
        view_dir = view or self.settings.images.default_view
        cache_key = (surface, seq_no, view_dir, level, tile_x, tile_y, tile_size, fmt)
        cached = self.tile_cache.get(cache_key)
        if cached:
            return cached
        # 1. 获取原始长带拼接图（每个 surface/seq_no 仅构建一次，复用缓存）
        mosaic = self._build_mosaic(surface, seq_no, view=view, limit=None, skip=0, stride=1)

        # 2. 针对不同 LOD 级别缓存缩放后的马赛克，避免每个瓦片重复 resize
        if level > 0:
            lod_key = ("mosaic_lod", surface, seq_no, view_dir, level)
            cached_lod = self.mosaic_cache.get(lod_key)
            if cached_lod:
                working = cached_lod
            else:
                scale = 1 / (2**level)
                target = (max(1, int(mosaic.width * scale)), max(1, int(mosaic.height * scale)))
                working = mosaic.resize(target, Image.Resampling.BILINEAR)
                # 缓存该 LOD 图，后续相同级别的瓦片直接复用
                self.mosaic_cache.put(lod_key, working.copy())
        else:
            working = mosaic
        left = tile_x * tile_size
        top = tile_y * tile_size
        # 限制裁剪区域在图像范围内，避免完全落在图像外导致全黑瓦片
        if left >= working.width or top >= working.height:
            raise FileNotFoundError(f"Tile ({tile_x}, {tile_y}) out of bounds for {surface} seq={seq_no}")
        right = min(left + tile_size, working.width)
        bottom = min(top + tile_size, working.height)
        tile = working.crop((left, top, right, bottom))
        data = encode_image(tile, fmt=fmt)
        self.tile_cache.put(cache_key, data)
        return data

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
        if cached:
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
        if cached:
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
        if cached:
            return open_image_from_bytes(cached, mode=self.mode)
        data = path.read_bytes()
        self.frame_cache.put(key, data)
        return open_image_from_bytes(data, mode=self.mode)
