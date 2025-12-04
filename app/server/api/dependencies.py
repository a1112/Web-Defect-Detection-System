from __future__ import annotations

from functools import lru_cache

from app.server import deps as core_deps
from app.server.services.defect_service import DefectService
from app.server.services.image_service import ImageService
from app.server.services.steel_service import SteelService


def get_steel_service() -> SteelService:
    return SteelService(core_deps.get_main_db)


@lru_cache()
def get_defect_service() -> DefectService:
    return DefectService(core_deps.get_defect_db)


@lru_cache()
def get_image_service() -> ImageService:
    return ImageService(core_deps.get_settings(), get_defect_service())

