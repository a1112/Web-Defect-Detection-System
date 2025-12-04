from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, validator

DEFAULT_CONFIG_NAME = "server.json"
SAMPLE_CONFIG_NAME = "server.sample.json"
ENV_CONFIG_KEY = "SERVER_CONFIG_PATH"
REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "configs"
LEGACY_CONFIG_DIR = Path(__file__).resolve().parent


class DatabaseSettings(BaseModel):
    drive: Literal["mysql", "sqlserver"] = "mysql"
    host: str = Field(default="127.0.0.1")
    port: Optional[int] = None
    user: str = Field(default="root")
    password: str = Field(default="nercar")
    charset: str = Field(default="utf8")
    database_type: str = Field(default="ncdplate")

    @property
    def resolved_port(self) -> int:
        if self.port:
            return self.port
        return 1433 if self.drive == "sqlserver" else 3306


class ImageSettings(BaseModel):
    top_root: Path
    bottom_root: Path
    default_view: str = Field(default="2D")
    file_extension: str = Field(default="jpg")
    max_cached_frames: int = Field(default=64, ge=1)
    max_cached_tiles: int = Field(default=256, ge=1)
    max_cached_mosaics: int = Field(default=8, ge=1)
    mode: str = Field(default="L", description="Pillow image mode, e.g. L/RGB")

    @validator("top_root", "bottom_root", pre=True)
    def _coerce_path(cls, value: str | Path) -> Path:
        return Path(value)


class ServerSettings(BaseModel):
    database: DatabaseSettings
    images: ImageSettings

    @classmethod
    def load(cls, explicit_path: str | Path | None = None) -> "ServerSettings":
        """
        Load settings from JSON file - priority order:
        1. Explicit path provided to load()
        2. SERVER_CONFIG_PATH environment variable
        3. configs/server.json (if present)
        4. configs/server.sample.json (fallback for local dev)
        """
        config_path = cls._resolve_path(explicit_path)
        with open(config_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return cls(**payload)

    @staticmethod
    def _resolve_path(explicit_path: str | Path | None = None) -> Path:
        candidate_paths: list[Path] = []
        if explicit_path:
            candidate_paths.append(Path(explicit_path))
        env_path = os.getenv(ENV_CONFIG_KEY)
        if env_path:
            candidate_paths.append(Path(env_path))
        candidate_paths.append(CONFIG_DIR / DEFAULT_CONFIG_NAME)
        candidate_paths.append(CONFIG_DIR / SAMPLE_CONFIG_NAME)
        candidate_paths.append(LEGACY_CONFIG_DIR / DEFAULT_CONFIG_NAME)
        candidate_paths.append(LEGACY_CONFIG_DIR / "settings.sample.json")
        for candidate in candidate_paths:
            if candidate and candidate.exists():
                return candidate
        raise FileNotFoundError(
            "No configuration file found. "
            "Provide SERVER_CONFIG_PATH or create configs/server.json."
        )


def ensure_config_file(explicit_path: str | Path | None = None) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    env_path = os.getenv(ENV_CONFIG_KEY)
    target = Path(explicit_path or env_path or (CONFIG_DIR / DEFAULT_CONFIG_NAME))
    if target.exists():
        return target
    if explicit_path or env_path:
        raise FileNotFoundError(f"Configuration file not found at {target}")
    sample_candidates = [
        CONFIG_DIR / SAMPLE_CONFIG_NAME,
        LEGACY_CONFIG_DIR / "settings.sample.json",
    ]
    for sample in sample_candidates:
        if sample.exists():
            target.write_text(sample.read_text(encoding="utf-8"), encoding="utf-8")
            return target
    raise FileNotFoundError(
        "No configuration file found. "
        "Provide SERVER_CONFIG_PATH or create configs/server.json."
    )
