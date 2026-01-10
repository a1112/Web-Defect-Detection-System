from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, validator

DEFAULT_CONFIG_NAME = "server.json"
SAMPLE_CONFIG_NAME = "server.sample.json"
ENV_CONFIG_KEY = "SERVER_CONFIG_PATH"
REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "configs"
TEMPLATE_DIR = CONFIG_DIR / "template"
CURRENT_DIR = CONFIG_DIR / "current"
LEGACY_CONFIG_DIR = Path(__file__).resolve().parent


def ensure_current_config_dir() -> Path:
    CURRENT_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("server.json", "map.json", "DefectClass.json"):
        target = CURRENT_DIR / name
        if target.exists():
            continue
        source = TEMPLATE_DIR / name
        if source.exists():
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return CURRENT_DIR


class DatabaseSettings(BaseModel):
    drive: Literal["mysql", "sqlserver", "sqlite"] = "mysql"
    host: str = Field(default="127.0.0.1")
    port: Optional[int] = None
    user: str = Field(default="root")
    password: str = Field(default="nercar")
    charset: str = Field(default="utf8")
    database_type: str = Field(default="ncdplate")
    management_database: str = Field(default="DefectDetectionDatabBase")
    sqlite_dir: Optional[Path] = Field(
        default=None,
        description="Directory containing SQLite backups named like {database}.db",
    )

    @property
    def resolved_port(self) -> int:
        if self.port:
            return self.port
        return 1433 if self.drive == "sqlserver" else 3306

    @validator("sqlite_dir", pre=True)
    def _coerce_sqlite_dir(cls, value: str | Path | None) -> Path | None:
        if value is None or value == "":
            return None
        return Path(value)


class ImageSettings(BaseModel):
    top_root: Path
    bottom_root: Path
    disk_cache_top_root: Optional[Path] = Field(default=None)
    disk_cache_bottom_root: Optional[Path] = Field(default=None)
    default_view: str = Field(default="2D")
    file_extension: str = Field(default="jpg")
    frame_width: int = Field(default=16384, ge=1)
    frame_height: int = Field(default=1024, ge=1)
    tile_max_level: int = Field(default=2, ge=0)
    tile_min_level: int = Field(default=0, ge=0)
    tile_default_size: Optional[int] = Field(default=None, ge=64)
    pixel_scale: float = Field(
        default=1.0,
        gt=0,
        description="Scale factor applied to image-space coordinates (e.g. 0.5 for half-resolution SMALL images).",
    )
    tile_prefetch_enabled: bool = Field(default=True)
    tile_prefetch_workers: int = Field(default=2, ge=1)
    tile_prefetch_ttl_seconds: int = Field(default=300, ge=1)
    tile_prefetch_clear_pending_on_seq_change: bool = Field(default=True)
    tile_prefetch_adjacent_tile_count: int = Field(default=1, ge=0, le=8)
    tile_prefetch_adjacent_tile_order: list[str] = Field(default_factory=lambda: ["right", "left", "down", "up"])
    tile_prefetch_cross_level_enabled: bool = Field(default=True)
    tile_prefetch_adjacent_seq_enabled: bool = Field(default=True)
    tile_prefetch_adjacent_seq_level4_count: int = Field(default=10, ge=0, le=200)
    tile_prefetch_adjacent_seq_level3_count: int = Field(default=20, ge=0, le=200)
    tile_prefetch_log_enabled: bool = Field(default=True)
    tile_prefetch_log_detail: Literal["summary", "task"] = Field(default="summary")
    mode: str = Field(default="L", description="Pillow image mode, e.g. L/RGB")

    @validator("top_root", "bottom_root", "disk_cache_top_root", "disk_cache_bottom_root", pre=True)
    def _coerce_path(cls, value: str | Path) -> Path:
        if value is None or value == "":
            return value
        return Path(value)

    @validator("tile_default_size", always=True)
    def _default_tile_size(cls, value: Optional[int], values: dict) -> int:
        if value is not None:
            return value
        frame_height = values.get("frame_height")
        if isinstance(frame_height, int) and frame_height > 0:
            return frame_height
        return 1024

    @validator("tile_prefetch_adjacent_tile_order", pre=True)
    def _coerce_adjacent_order(cls, value):
        if value is None:
            return ["right", "left", "down", "up"]
        if isinstance(value, str):
            # Support comma-separated strings in JSON/env overrides.
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @validator("tile_prefetch_adjacent_tile_order")
    def _validate_adjacent_order(cls, value: list[str]) -> list[str]:
        allowed = {
            "right",
            "left",
            "down",
            "up",
            "down_right",
            "down_left",
            "up_right",
            "up_left",
        }
        normalized: list[str] = []
        for item in value or []:
            key = str(item).strip().lower()
            if not key:
                continue
            if key not in allowed:
                raise ValueError(f"Unsupported tile_prefetch_adjacent_tile_order entry '{item}'")
            if key not in normalized:
                normalized.append(key)
        return normalized


class ServerSettings(BaseModel):
    database: DatabaseSettings
    images: ImageSettings
    cache: "CacheSettings"
    config_center_url: Optional[str] = Field(
        default=None,
        description="Config center base URL used for status heartbeat when DEFECT_CONFIG_CENTER_URL is unset.",
    )
    test_mode: bool = Field(default=False, description="Enable local TestData-backed mode (SQLite + local images).")
    testdata_dir: Optional[Path] = Field(default=None, description="Path to TestData directory used in test mode.")

    @validator("testdata_dir", pre=True)
    def _coerce_testdata_dir(cls, value: str | Path | None) -> Path | None:
        if value is None or value == "":
            return None
        return Path(value)

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
        base_path = CURRENT_DIR / DEFAULT_CONFIG_NAME
        if base_path.exists() and base_path.resolve() != config_path.resolve():
            base_payload = json.loads(base_path.read_text(encoding="utf-8"))
            payload = _deep_merge(base_payload, payload)
        return cls(**payload)

    @staticmethod
    def _resolve_path(explicit_path: str | Path | None = None) -> Path:
        candidate_paths: list[Path] = []
        if explicit_path:
            candidate_paths.append(Path(explicit_path))
        env_path = os.getenv(ENV_CONFIG_KEY)
        if env_path:
            candidate_paths.append(Path(env_path))
        ensure_current_config_dir()
        candidate_paths.append(CURRENT_DIR / DEFAULT_CONFIG_NAME)
        candidate_paths.append(TEMPLATE_DIR / DEFAULT_CONFIG_NAME)
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
    ensure_current_config_dir()
    current_candidate = CURRENT_DIR / DEFAULT_CONFIG_NAME
    if current_candidate.exists():
        return current_candidate
    template_candidate = TEMPLATE_DIR / DEFAULT_CONFIG_NAME
    if template_candidate.exists():
        current_candidate.write_text(template_candidate.read_text(encoding="utf-8"), encoding="utf-8")
        return current_candidate
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


class CacheSettings(BaseModel):
    max_frames: int = Field(default=64, ge=-1)
    max_tiles: int = Field(default=256, ge=-1)
    max_mosaics: int = Field(default=8, ge=-1)
    max_defect_crops: int = Field(default=256, ge=-1)
    ttl_seconds: int = Field(default=120, ge=1)
    defect_cache_enabled: bool = Field(
        default=True,
        description="是否启用缺陷裁剪结果的磁盘缓存（依赖 disk_cache_enabled 一并生效）。",
    )
    defect_cache_expand: int = Field(
        default=100,
        ge=0,
        le=512,
        description="缺陷缓存最大裁剪保留：缺陷裁剪时的默认扩展像素。",
    )
    disk_cache_enabled: bool = Field(default=False)
    disk_cache_max_records: int = Field(default=20000, ge=1)
    disk_cache_scan_interval_seconds: int = Field(default=5, ge=1)
    disk_cache_cleanup_interval_seconds: int = Field(default=60, ge=1)
    disk_precache_enabled: bool = Field(default=False)
    disk_precache_levels: int = Field(default=1, ge=1)
    disk_precache_workers: int = Field(default=2, ge=1)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
