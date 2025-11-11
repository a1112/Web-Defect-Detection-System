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
        cache_key = (surface, seq_no, view or self.settings.images.default_view, level, tile_x, tile_y, tile_size, fmt)
        cached = self.tile_cache.get(cache_key)
        if cached:
            return cached
        mosaic = self._build_mosaic(surface, seq_no, view=view)
        working = mosaic
        if level > 0:
            scale = 1 / (2**level)
            target = (max(1, int(mosaic.width * scale)), max(1, int(mosaic.height * scale)))
            working = mosaic.resize(target, Image.Resampling.BILINEAR)
        left = tile_x * tile_size
        top = tile_y * tile_size
        tile = working.crop((left, top, left + tile_size, top + tile_size))
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
        images = [self._load_frame_from_path(path) for path in frames]
        width = max(img.width for img in images)
        total_height = sum(img.height for img in images)
        mosaic = Image.new("RGB", (width, total_height))
        current_y = 0
        for img in images:
            mosaic.paste(img, (0, current_y))
            current_y += img.height
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
