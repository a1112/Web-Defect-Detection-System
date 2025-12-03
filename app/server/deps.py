from __future__ import annotations

from functools import lru_cache

from sqlalchemy.orm import Session

from .config.settings import ServerSettings, ensure_config_file
from .database import get_defect_session, get_main_session


@lru_cache()
def get_settings() -> ServerSettings:
    ensure_config_file()
    return ServerSettings.load()


def get_main_db() -> Session:
    settings = get_settings()
    return get_main_session(settings)


def get_defect_db() -> Session:
    settings = get_settings()
    return get_defect_session(settings)
