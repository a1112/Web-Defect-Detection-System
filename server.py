from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import multiprocessing as mp
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import json
from typing import Any
from threading import Lock

import uvicorn

from app.server.config.settings import ENV_CONFIG_KEY
from app.server.config_center import create_app
from app.server.net_table import load_map_config, build_config_for_line

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = REPO_ROOT / "configs"
TEMPLATE_DIR = CONFIG_DIR / "template"
CURRENT_DIR = CONFIG_DIR / "current"
TEST_MODE_ENV = "DEFECT_TEST_MODE"
TESTDATA_DIR_ENV = "DEFECT_TESTDATA_DIR"


def _resolve_template() -> Path:
    candidate = CURRENT_DIR / "server.json"
    if candidate.exists():
        return candidate
    fallback = TEMPLATE_DIR / "server.json"
    return fallback


def _line_port(line: dict[str, Any], fallback: int) -> int:
    for key in ("port", "listen_port", "service_port"):
        value = line.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return fallback


def _view_port_offset(view_key: str, view_config: dict[str, Any] | None, index: int) -> int:
    if isinstance(view_config, dict):
        value = view_config.get("port_offset")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    if view_key in ("2D", "default"):
        return 0
    if view_key == "small":
        return 100
    return 100 * (index + 1)


def _line_host(line: dict[str, Any]) -> str:
    host = line.get("listen_host") or line.get("host") or "0.0.0.0"
    return str(host)


def _ensure_testdata_dir(testdata_dir: Path) -> None:
    required = [
        testdata_dir / "DataBase",
        testdata_dir / "Image",
    ]
    missing = [p for p in required if not p.exists()]
    if not missing:
        return
    for path in missing:
        logger.error("Missing TestData path: %s", path)
    raise SystemExit(1)


def _run_uvicorn(
    config_path: Path,
    host: str,
    port: int,
    defect_class_path: Path | None,
    line_name: str,
    line_key: str,
    line_kind: str,
    testdata_dir: Path | None,
    reload: bool,
) -> None:
    _configure_logging(line_name)
    _log_database_url(config_path, line_name)
    os.environ[ENV_CONFIG_KEY] = str(config_path.resolve())
    os.environ["DEFECT_LINE_NAME"] = line_name
    os.environ["DEFECT_LINE_KEY"] = line_key
    os.environ["DEFECT_LINE_KIND"] = line_kind
    os.environ["DEFECT_LINE_HOST"] = host
    os.environ["DEFECT_LINE_PORT"] = str(port)
    os.environ.setdefault("DEFECT_CONFIG_CENTER_URL", "http://127.0.0.1:8119")
    if defect_class_path:
        os.environ["DEFECT_CLASS_PATH"] = str(defect_class_path.resolve())
    if testdata_dir is not None:
        os.environ[TEST_MODE_ENV] = "true"
        os.environ[TESTDATA_DIR_ENV] = str(testdata_dir)
    uvicorn.run(
        "app.server.main:app",
        host=host,
        port=port,
        reload=reload,
        workers=1,
    )


def _sanitize_line_name(line_name: str) -> str:
    if not line_name:
        return "default"
    cleaned = re.sub(r'[<>:"/\\\\|?*\\x00-\\x1F]', "_", line_name.strip())
    return cleaned or "default"


class _MaxLevelFilter(logging.Filter):
    def __init__(self, max_level: int) -> None:
        super().__init__()
        self._max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self._max_level


def _configure_logging(line_name: str) -> None:
    log_dir = REPO_ROOT / "error_log" / _sanitize_line_name(line_name)
    log_dir.mkdir(parents=True, exist_ok=True)
    error_path = log_dir / "error.log"
    info_path = log_dir / "server.log"

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(processName)s %(name)s: %(message)s"
    )

    error_handler = logging.handlers.TimedRotatingFileHandler(
        error_path,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
        delay=True,
    )
    error_handler.suffix = "%Y-%m-%d"
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    info_handler = logging.handlers.TimedRotatingFileHandler(
        info_path,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
        delay=True,
    )
    info_handler.suffix = "%Y-%m-%d"
    info_handler.setLevel(logging.INFO)
    info_handler.addFilter(_MaxLevelFilter(logging.WARNING))
    info_handler.setFormatter(formatter)

    console_error_handler = logging.StreamHandler()
    console_error_handler.setLevel(logging.ERROR)
    console_error_handler.setFormatter(formatter)

    console_info_handler = logging.StreamHandler()
    console_info_handler.setLevel(logging.INFO)
    console_info_handler.addFilter(_MaxLevelFilter(logging.WARNING))
    console_info_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.addHandler(error_handler)
    root_logger.addHandler(info_handler)
    root_logger.addHandler(console_error_handler)
    root_logger.addHandler(console_info_handler)


def _log_database_url(config_path: Path, line_name: str) -> None:
    logger = logging.getLogger(__name__)
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        database = payload.get("database") if isinstance(payload, dict) else {}
        if not isinstance(database, dict):
            database = {}
        drive = str(database.get("drive") or "mysql").lower()
        host = database.get("host") or "127.0.0.1"
        port = database.get("port")
        user = database.get("user") or "root"
        password = database.get("password") or ""
        charset = database.get("charset") or "utf8"
        db_name = database.get("database_type") or "ncdplate"
        if drive == "mysql":
            url = f"mysql+pymysql://{user}:{password}@{host}:{port or 3306}/{db_name}?charset={charset}"
        elif drive == "sqlserver":
            url = f"mssql+pymssql://{user}:{password}@{host}:{port or 1433}/{db_name}"
        elif drive == "sqlite":
            sqlite_dir = database.get("sqlite_dir")
            sqlite_path = Path(sqlite_dir) / f"{db_name}.db" if sqlite_dir else Path(f"{db_name}.db")
            url = f"sqlite:///{sqlite_path}"
        else:
            url = f"{drive}://{user}:{password}@{host}:{port}/{db_name}"
        logger.info("Line '%s' database URL: %s", line_name, url)
    except Exception:
        logger.exception("Failed to resolve database URL for line '%s' from %s", line_name, config_path)


@dataclass
class LineProcess:
    key: str
    name: str
    host: str
    port: int
    profile: str | None
    config_path: Path
    defect_class_path: Path | None
    ip: str | None
    kind: str
    testdata_dir: Path | None
    process: mp.Process | None = None


@dataclass
class ApiStatusEntry:
    key: str
    kind: str
    online: bool
    latest_timestamp: datetime | None
    last_seen: datetime
    name: str | None = None
    host: str | None = None
    port: int | None = None
    pid: int | None = None


class LineProcessManager:
    def __init__(self, *, reload: bool = False) -> None:
        self._lines: dict[str, list[LineProcess]] = {}
        self._api_status: dict[tuple[str, str], ApiStatusEntry] = {}
        self._status_lock = Lock()
        self._status_ttl_seconds = int(os.getenv("DEFECT_API_STATUS_TTL_SECONDS", "60"))
        self._reload = reload

    def add_line(self, line: LineProcess) -> None:
        self._lines.setdefault(line.key, []).append(line)

    def start_all(self) -> None:
        for group in self._lines.values():
            for line in group:
                self._start_line(line)

    def restart_all(self) -> int:
        count = 0
        for group in self._lines.values():
            for line in group:
                if self._restart_line(line):
                    count += 1
        return count

    def restart_line(self, name: str) -> bool:
        group = self._lines.get(name)
        if not group:
            return False
        for line in group:
            self._restart_line(line)
        return True

    def get_api_list(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for key, group in self._lines.items():
            main_proc = next((item for item in group if item.kind in ("2D", "default")), None)
            small_proc = next((item for item in group if item.kind == "small"), None)
            view_items = [
                {
                    "view": item.kind,
                    "port": item.port,
                    "path": "/api" if item.kind in ("2D", "default") else f"/{item.kind}--api",
                }
                for item in group
            ]
            process = main_proc.process if main_proc else None
            status = self._get_cached_status(key)
            items.append(
                {
                    "key": key,
                    "name": main_proc.name if main_proc else (group[0].name if group else key),
                    "host": main_proc.host if main_proc else (group[0].host if group else "0.0.0.0"),
                    "port": main_proc.port if main_proc else None,
                    "small_port": small_proc.port if small_proc else None,
                    "ip": main_proc.ip if main_proc else (group[0].ip if group else None),
                    "profile": main_proc.profile if main_proc else None,
                    "pid": process.pid if process else None,
                    "running": bool(process and process.is_alive()),
                    "online": status.get("online"),
                    "latest_timestamp": status.get("latest_timestamp"),
                    "latest_age_seconds": status.get("latest_age_seconds"),
                    "path": f"/api/{key}",
                    "small_path": f"/small--api/{key}",
                    "views": view_items,
                }
            )
        return items

    def update_api_status(self, status: dict[str, Any]) -> None:
        key = str(status.get("key") or "")
        if not key:
            return
        kind = str(status.get("kind") or "default")
        latest_timestamp = status.get("latest_timestamp")
        if isinstance(latest_timestamp, str):
            latest_timestamp = _parse_iso_timestamp(latest_timestamp)
        if not isinstance(latest_timestamp, datetime):
            latest_timestamp = None
        online_value = status.get("online")
        online = bool(online_value) if online_value is not None else True
        entry = ApiStatusEntry(
            key=key,
            kind=kind,
            online=online,
            latest_timestamp=latest_timestamp,
            last_seen=datetime.utcnow(),
            name=status.get("name"),
            host=status.get("host"),
            port=_coerce_int(status.get("port")),
            pid=_coerce_int(status.get("pid")),
        )
        with self._status_lock:
            self._api_status[(key, kind)] = entry

    def _start_line(self, line: LineProcess) -> None:
        if line.process and line.process.is_alive():
            return
        process = mp.Process(
            target=_run_uvicorn,
            args=(
                line.config_path,
                line.host,
                line.port,
                line.defect_class_path,
                line.name,
                line.key,
                line.kind,
                line.testdata_dir,
                self._reload,
            ),
            daemon=False,
            name=line.name or None,
        )
        process.start()
        line.process = process

    def _restart_line(self, line: LineProcess) -> bool:
        if line.process and line.process.is_alive():
            line.process.terminate()
            line.process.join(timeout=10)
        self._start_line(line)
        return True

    def _get_cached_status(self, key: str) -> dict[str, Any]:
        now = datetime.utcnow()
        with self._status_lock:
            status = (
                self._api_status.get((key, "2D"))
                or self._api_status.get((key, "default"))
                or self._api_status.get((key, "small"))
            )
        if not status:
            return {"online": False, "latest_timestamp": None, "latest_age_seconds": None}
        age_since_seen = (now - status.last_seen).total_seconds()
        stale = age_since_seen > self._status_ttl_seconds
        online = status.online and not stale
        latest_age_seconds = None
        latest_timestamp = status.latest_timestamp
        if latest_timestamp:
            latest_age_seconds = max(0, int((now - latest_timestamp).total_seconds()))
        return {
            "online": online,
            "latest_timestamp": latest_timestamp.isoformat() if latest_timestamp else None,
            "latest_age_seconds": latest_age_seconds,
        }


def _parse_iso_timestamp(value: str) -> datetime | None:
    try:
        cleaned = value.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        parsed = datetime.fromisoformat(cleaned)
        return parsed.replace(tzinfo=None)
    except ValueError:
        return None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Net table multi-line server launcher")
    parser.add_argument(
        "--test_data",
        action="store_true",
        help="Use TestData as data source (SQLite + local images).",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=False,
        help="Enable auto-reload for each API service (development only).",
    )
    args = parser.parse_args()

    testdata_dir: Path | None = None
    if args.test_data:
        testdata_dir = (REPO_ROOT / "TestData").resolve()
        _ensure_testdata_dir(testdata_dir)

    config = load_map_config()
    defaults = config.get("defaults") or {}
    lines: list[dict[str, Any]] = config.get("lines") or []
    views: dict[str, Any] = config.get("views") or {}
    if not lines:
        raise RuntimeError("No lines found; check configs/current/map.json")

    manager = LineProcessManager(reload=args.reload)
    base_port = 8200
    for idx, line in enumerate(lines):
        mode = (line.get("mode") or "direct").lower()
        if mode != "direct":
            continue
        template = _resolve_template()
        if not template.exists():
            raise FileNotFoundError(f"Template config not found: {template}")
        port = _line_port(line, base_port + idx)
        host = _line_host(line)
        line_name = str(line.get("name") or "")
        line_key = str(line.get("key") or line_name)
        defect_class_path = None
        if line_name:
            candidate = CURRENT_DIR / line_name / "DefectClass.json"
            if candidate.exists():
                defect_class_path = candidate
        if defect_class_path is None:
            fallback = CURRENT_DIR / "DefectClass.json"
            if fallback.exists():
                defect_class_path = fallback

        view_items = list(views.items()) if isinstance(views, dict) and views else [("2D", {})]
        for view_index, (view_key, view_config) in enumerate(view_items):
            offset = _view_port_offset(view_key, view_config if isinstance(view_config, dict) else None, view_index)
            view_port = port + offset
            view_payload = view_config if isinstance(view_config, dict) else {}
            config_path = build_config_for_line(
                line,
                template,
                defaults=defaults,
                view_name=view_key,
                view_overrides=view_payload,
            )
            logger.info(
                "Starting line '%s' view '%s' on %s:%s with %s",
                line_name,
                view_key,
                host,
                view_port,
                template.name,
            )
            manager.add_line(
                LineProcess(
                    key=line_key,
                    name=line_name,
                    host=host,
                    port=view_port,
                    profile=line.get("profile") or line.get("api_profile"),
                    config_path=config_path,
                    defect_class_path=defect_class_path,
                    ip=line.get("ip"),
                    kind=view_key,
                    testdata_dir=testdata_dir,
                )
            )

    manager.start_all()
    config_app = create_app(manager)
    uvicorn.run(config_app, host="0.0.0.0", port=8119, reload=False, workers=1)


if __name__ == "__main__":
    mp.freeze_support()
    main()
