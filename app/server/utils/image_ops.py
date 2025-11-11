from __future__ import annotations

import io
from typing import Optional, Tuple

from PIL import Image

Box = Tuple[int, int, int, int]


def open_image_from_bytes(data: bytes, mode: str | None = "RGB") -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    if mode:
        return convert_mode(image, mode)
    return image


def convert_mode(image: Image.Image, mode: str) -> Image.Image:
    if image.mode == mode:
        return image
    return image.convert(mode)


def resize_image(
    image: Image.Image, width: Optional[int] = None, height: Optional[int] = None
) -> Image.Image:
    if not width and not height:
        return image
    if width and height:
        target = (width, height)
    elif width:
        ratio = width / image.width
        target = (width, int(image.height * ratio))
    else:
        ratio = height / image.height  # type: ignore[operator]
        target = (int(image.width * ratio), height)  # type: ignore[arg-type]
    return image.resize(target, Image.Resampling.LANCZOS)


def encode_image(image: Image.Image, fmt: str = "JPEG", quality: int = 90) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt.upper(), quality=quality)
    return buffer.getvalue()


def expand_box(box: Box, expand: int, max_width: int, max_height: int) -> Box:
    if not expand:
        return clamp_box(box, max_width, max_height)
    left, top, right, bottom = box
    left -= expand
    top -= expand
    right += expand
    bottom += expand
    return clamp_box((left, top, right, bottom), max_width, max_height)


def clamp_box(box: Box, max_width: int, max_height: int) -> Box:
    left, top, right, bottom = box
    left = max(0, min(left, max_width))
    right = max(0, min(right, max_width))
    top = max(0, min(top, max_height))
    bottom = max(0, min(bottom, max_height))
    if right <= left:
        right = min(max_width, left + 1)
    if bottom <= top:
        bottom = min(max_height, top + 1)
    return left, top, right, bottom
