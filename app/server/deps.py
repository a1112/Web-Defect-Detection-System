from __future__ import annotations

from functools import lru_cache

from .config.settings import ServerSettings, ensure_config_file
from .database import get_database


@lru_cache()
def get_settings() -> ServerSettings:
    ensure_config_file()
    return ServerSettings.load()


def get_dbm():
    settings = get_settings()
    return get_database(settings)
