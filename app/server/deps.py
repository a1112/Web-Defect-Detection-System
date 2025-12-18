from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

from sqlalchemy.orm import Session

from .config.settings import ServerSettings, ensure_config_file
from .database import get_defect_session, get_main_session

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
                }
            ),
        }
    )


def get_main_db() -> Session:
    settings = get_settings()
    return get_main_session(settings)


def get_defect_db() -> Session:
    settings = get_settings()
    return get_defect_session(settings)
