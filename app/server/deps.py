from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

from typing import Generator

from sqlalchemy.orm import Session

from .config.settings import ServerSettings, ensure_config_file
from .database import get_defect_session, get_main_session, get_management_session
from .rbac.manager import bootstrap_management

TEST_MODE_ENV = "DEFECT_TEST_MODE"
TESTDATA_DIR_ENV = "DEFECT_TESTDATA_DIR"
DEFAULT_TESTDATA_DIR = Path(__file__).resolve().parents[2] / "TestData"


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@lru_cache()
def get_settings() -> ServerSettings:
    ensure_config_file()
    settings = ServerSettings.load()
    if not _is_truthy(os.getenv(TEST_MODE_ENV)):
        return settings

    testdata_dir = Path(os.getenv(TESTDATA_DIR_ENV, str(DEFAULT_TESTDATA_DIR))).resolve()
    sqlite_dir = testdata_dir / "DataBase"
    image_root = testdata_dir / "Image"

    return settings.model_copy(
        update={
            "test_mode": True,
            "testdata_dir": testdata_dir,
            "database": settings.database.model_copy(
                update={
                    "drive": "sqlite",
                    "sqlite_dir": sqlite_dir,
                }
            ),
            "images": settings.images.model_copy(
                update={
                    "top_root": image_root,
                    "bottom_root": image_root,
                    # In TestData mode, prefer local disk cache data
                    # by pointing disk cache roots to the same Image tree.
                    "disk_cache_top_root": image_root,
                    "disk_cache_bottom_root": image_root,
                }
            ),
        }
    )


def get_main_db() -> Generator[Session, None, None]:
    settings = get_settings()
    session = get_main_session(settings)
    try:
        yield session
    finally:
        session.close()


def get_defect_db() -> Generator[Session, None, None]:
    settings = get_settings()
    session = get_defect_session(settings)
    try:
        yield session
    finally:
        session.close()


def get_management_db() -> Generator[Session, None, None]:
    settings = get_settings()
    db_settings = settings.database
    if db_settings.drive != "sqlite" and "{ip}" in (db_settings.host or ""):
        fallback_dir = Path(__file__).resolve().parents[2] / "work" / "local_db"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        fallback_settings = settings.model_copy(
            update={
                "database": db_settings.model_copy(
                    update={"drive": "sqlite", "sqlite_dir": fallback_dir}
                )
            }
        )
        session = get_management_session(fallback_settings)
        try:
            bootstrap_management(fallback_settings, session)
            yield session
        finally:
            session.close()
        return
    session = get_management_session(settings)
    try:
        bootstrap_management(settings, session)
        yield session
    finally:
        session.close()
