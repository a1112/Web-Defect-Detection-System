from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
import subprocess
import multiprocessing as mp
import psutil # type: ignore
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import json
from typing import Any
from threading import Lock
from collections import deque

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
LOG_CONFIG_KEYS = {
    "root_dir",
    "path_template",
    "server_name",
    "level",
    "format",
    "rotation_when",
    "backup_count",
    "modules",
}


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
    _configure_logging(
        line_name,
        line_key=line_key,
        line_kind=line_kind,
        config_path=config_path,
    )
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


def _sanitize_log_segment(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    cleaned = re.sub(r'[<>:"/\\\\|?*\\x00-\\x1F]', "_", str(value).strip())
    return cleaned or fallback


class _MaxLevelFilter(logging.Filter):
    def __init__(self, max_level: int) -> None:
        super().__init__()
        self._max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self._max_level


def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _merge_dict(dict(base[key]), value)
        else:
            base[key] = value
    return base


def _filter_log_config(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return {key: value for key, value in payload.items() if key in LOG_CONFIG_KEYS}


def _resolve_log_dir(
    log_config: dict[str, Any],
    *,
    line_key: str,
    line_name: str,
    view: str,
    server_name: str,
    default_root: Path,
) -> Path:
    root_dir = log_config.get("root_dir") or default_root
    root_path = Path(root_dir)
    if not root_path.is_absolute():
        root_path = (REPO_ROOT.parent / root_path).resolve()
    template = log_config.get("path_template") or "{root}/{line_key}/{view}/{server_name}"
    context = {
        "root": str(root_path),
        "line_key": _sanitize_log_segment(line_key, "default"),
        "line_name": _sanitize_log_segment(line_name, "default"),
        "view": _sanitize_log_segment(view, "default"),
        "server_name": _sanitize_log_segment(server_name, "api"),
    }
    try:
        rendered = template.format(**context)
    except Exception:
        rendered = str(root_path / f"{context['line_key']}/{context['view']}/{context['server_name']}")
    if "{root}" in template:
        return Path(rendered)
    return root_path / rendered


def _configure_logging(
    line_name: str,
    *,
    line_key: str | None = None,
    line_kind: str | None = None,
    config_path: Path | None = None,
    log_overrides: dict[str, Any] | None = None,
    server_name: str | None = None,
    default_root: Path | None = None,
) -> None:
    log_config: dict[str, Any] = {}
    default_view: str | None = None
    if config_path and config_path.exists():
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            log_config = payload.get("log") if isinstance(payload.get("log"), dict) else {}
            images_payload = payload.get("images") if isinstance(payload.get("images"), dict) else {}
            default_view = images_payload.get("default_view") if images_payload else None
        except Exception:
            log_config = {}
            default_view = None
    if log_overrides:
        log_config = _merge_dict(dict(log_config), log_overrides)
    log_config = _filter_log_config(log_config)

    if line_kind:
        cleaned_kind = str(line_kind).strip()
        if not cleaned_kind or set(cleaned_kind) == {"_"}:
            line_kind = None
    if not line_kind and default_view:
        line_kind = str(default_view)

    effective_line_key = line_key or line_name or "default"
    effective_view = line_kind or default_view or "default"
    effective_server_name = (
        server_name
        or log_config.get("server_name")
        or "api"
    )
    log_dir = _resolve_log_dir(
        log_config,
        line_key=effective_line_key,
        line_name=line_name,
        view=effective_view,
        server_name=effective_server_name,
        default_root=default_root or (REPO_ROOT.parent / "logs" / "api_log"),
    )
    log_dir.mkdir(parents=True, exist_ok=True)
    error_path = log_dir / "error.log"
    info_path = log_dir / "server.log"

    formatter = logging.Formatter(
        str(
            log_config.get("format")
            or "%(asctime)s %(levelname)s %(processName)s %(name)s: %(message)s"
        )
    )
    level = str(log_config.get("level") or "INFO").upper()
    when = str(log_config.get("rotation_when") or "midnight")
    backup_count = int(log_config.get("backup_count") or 30)

    error_handler = logging.handlers.TimedRotatingFileHandler(
        error_path,
        when=when,
        interval=1,
        backupCount=backup_count,
        encoding="utf-8",
        delay=True,
    )
    error_handler.suffix = "%Y-%m-%d"
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    info_handler = logging.handlers.TimedRotatingFileHandler(
        info_path,
        when=when,
        interval=1,
        backupCount=backup_count,
        encoding="utf-8",
        delay=True,
    )
    info_handler.suffix = "%Y-%m-%d"
    info_handler.setLevel(level)
    info_handler.addFilter(_MaxLevelFilter(logging.WARNING))
    info_handler.setFormatter(formatter)

    console_error_handler = logging.StreamHandler()
    console_error_handler.setLevel(logging.ERROR)
    console_error_handler.setFormatter(formatter)

    console_info_handler = logging.StreamHandler()
    console_info_handler.setLevel(level)
    console_info_handler.addFilter(_MaxLevelFilter(logging.WARNING))
    console_info_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(info_handler)
    root_logger.addHandler(console_error_handler)
    root_logger.addHandler(console_info_handler)

    modules = log_config.get("modules") if isinstance(log_config.get("modules"), dict) else {}
    if modules:
        _configure_module_logs(
            modules,
            log_dir=log_dir,
            base_level=level,
            base_format=formatter,
            base_when=when,
            base_backup=backup_count,
        )


def _configure_module_logs(
    modules: dict[str, Any],
    *,
    log_dir: Path,
    base_level: str,
    base_format: logging.Formatter,
    base_when: str,
    base_backup: int,
) -> None:
    for name, module_cfg in modules.items():
        if module_cfg is False:
            continue
        if module_cfg is True:
            module_cfg = {"enabled": True}
        if not isinstance(module_cfg, dict):
            continue
        if not module_cfg.get("enabled", False):
            continue
        logger_name = _resolve_module_logger_name(name, module_cfg)
        module_logger = logging.getLogger(logger_name)
        module_level = str(module_cfg.get("level") or base_level).upper()
        module_logger.setLevel(module_level)

        module_path = _resolve_module_log_path(log_dir, name, module_cfg)
        module_path.parent.mkdir(parents=True, exist_ok=True)
        if _has_handler(module_logger, module_path):
            continue
        module_formatter = logging.Formatter(
            str(module_cfg.get("format") or base_format._fmt)
        )
        when = str(module_cfg.get("rotation_when") or base_when)
        backup_count = int(module_cfg.get("backup_count") or base_backup)
        handler = logging.handlers.TimedRotatingFileHandler(
            module_path,
            when=when,
            interval=1,
            backupCount=backup_count,
            encoding="utf-8",
            delay=True,
        )
        handler.suffix = "%Y-%m-%d"
        handler.setLevel(module_level)
        handler.setFormatter(module_formatter)
        module_logger.addHandler(handler)


def _resolve_module_log_path(log_dir: Path, name: str, module_cfg: dict[str, Any]) -> Path:
    path_value = module_cfg.get("path")
    if path_value:
        path = Path(str(path_value))
        if path.is_absolute():
            return path
        return log_dir / path
    safe_name = _sanitize_log_segment(name, "module")
    return log_dir / safe_name / "log.log"


def _resolve_module_logger_name(name: str, module_cfg: dict[str, Any]) -> str:
    alias = module_cfg.get("logger") if isinstance(module_cfg, dict) else None
    if alias:
        return str(alias)
    aliases = {
        "image_service": "app.server.services.image_service",
        "disk_image_cache": "app.server.cache.disk_image_cache",
        "cache_generate": "status.cache_generate",
    }
    return aliases.get(name, name)


def _has_handler(logger: logging.Logger, path: Path) -> bool:
    target = str(path.resolve())
    for handler in logger.handlers:
        if isinstance(handler, logging.handlers.TimedRotatingFileHandler):
            try:
                if str(Path(handler.baseFilename).resolve()) == target:
                    return True
            except Exception:
                continue
    return False


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


@dataclass
class ServiceStatusEntry:
    name: str
    label: str | None
    priority: int
    state: str
    message: str | None
    data: dict[str, Any]
    updated_at: datetime
    last_seen: datetime


@dataclass
class ServiceLogEntry:
    service: str
    log_id: int
    time: str
    level: str
    message: str
    data: dict[str, Any]


class LineProcessManager:
    def __init__(self, *, reload: bool = False) -> None:
        self._lines: dict[str, list[LineProcess]] = {}
        self._api_status: dict[tuple[str, str], ApiStatusEntry] = {}
        self._status_lock = Lock()
        self._status_ttl_seconds = int(os.getenv("DEFECT_API_STATUS_TTL_SECONDS", "60"))
        self._service_status: dict[tuple[str, str], dict[str, ServiceStatusEntry]] = {}
        self._service_logs: dict[tuple[str, str], dict[str, deque[ServiceLogEntry]]] = {}
        self._service_log_last_id: dict[tuple[str, str], dict[str, int]] = {}
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
            services = status.get("services") or []
            if isinstance(services, list):
                service_map = self._service_status.setdefault((key, kind), {})
                for item in services:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "")
                    if not name:
                        continue
                    updated_at = item.get("updated_at")
                    if isinstance(updated_at, str):
                        parsed = _parse_iso_timestamp(updated_at)
                        updated_at_dt = parsed or datetime.utcnow()
                    else:
                        updated_at_dt = datetime.utcnow()
                    service_map[name] = ServiceStatusEntry(
                        name=name,
                        label=item.get("label"),
                        priority=int(item.get("priority") or 0),
                        state=str(item.get("state") or "ready"),
                        message=item.get("message"),
                        data=item.get("data") if isinstance(item.get("data"), dict) else {},
                        updated_at=updated_at_dt,
                        last_seen=datetime.utcnow(),
                    )
            logs = status.get("logs") or []
            if isinstance(logs, list):
                log_map = self._service_logs.setdefault((key, kind), {})
                last_id_map = self._service_log_last_id.setdefault((key, kind), {})
                for item in logs:
                    if not isinstance(item, dict):
                        continue
                    service = str(item.get("service") or "")
                    if not service:
                        continue
                    log_id = _coerce_int(item.get("id")) or 0
                    last_id = last_id_map.get(service, 0)
                    if log_id <= last_id:
                        continue
                    last_id_map[service] = log_id
                    buffer = log_map.setdefault(service, deque(maxlen=500))
                    buffer.append(
                        ServiceLogEntry(
                            service=service,
                            log_id=log_id,
                            time=str(item.get("time") or ""),
                            level=str(item.get("level") or "info"),
                            message=str(item.get("message") or ""),
                            data=item.get("data") if isinstance(item.get("data"), dict) else {},
                        )
                    )

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

    def get_status_items(self, line_key: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        with self._status_lock:
            for key, group in self._lines.items():
                if line_key and key != line_key:
                    continue
                for proc in group:
                    if kind and proc.kind != kind:
                        continue
                    status = self._api_status.get((key, proc.kind))
                    latest_age_seconds = None
                    latest_timestamp = None
                    if status and status.latest_timestamp:
                        latest_timestamp = status.latest_timestamp.isoformat()
                        latest_age_seconds = max(
                            0, int((datetime.utcnow() - status.latest_timestamp).total_seconds())
                        )
                    services = list(self._service_status.get((key, proc.kind), {}).values())
                    services_sorted = sorted(
                        services,
                        key=lambda item: (item.priority, item.updated_at),
                        reverse=True,
                    )
                    items.append(
                        {
                            "key": key,
                            "name": proc.name,
                            "kind": proc.kind,
                            "host": proc.host,
                            "port": proc.port,
                            "pid": status.pid if status else None,
                            "online": status.online if status else None,
                            "latest_timestamp": latest_timestamp,
                            "latest_age_seconds": latest_age_seconds,
                            "services": [
                                {
                                    "name": item.name,
                                    "label": item.label,
                                    "priority": item.priority,
                                    "state": item.state,
                                    "message": item.message,
                                    "data": item.data,
                                    "updated_at": item.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
                                }
                                for item in services_sorted
                            ],
                        }
                    )
        return items

    def _select_simple(self, services: list[ServiceStatusEntry]) -> dict[str, Any] | None:
        if not services:
            return None

        def _weight(state: str) -> int:
            lowered = (state or "ready").lower()
            if lowered == "error":
                return 3
            if lowered == "warning":
                return 2
            if lowered == "running":
                return 1
            return 0

        def _pick(candidates: list[ServiceStatusEntry]) -> ServiceStatusEntry | None:
            if not candidates:
                return None
            return max(
                candidates,
                key=lambda item: (
                    item.priority,
                    _weight(item.state),
                    item.updated_at,
                ),
            )

        errors = [item for item in services if (item.state or "").lower() == "error"]
        selected = _pick(errors)
        if not selected:
            running = [item for item in services if (item.state or "").lower() == "running"]
            selected = _pick(running)
        if not selected:
            image_service = next((item for item in services if item.name == "image_generate"), None)
            if image_service and image_service.message and image_service.message != "系统就绪":
                selected = image_service
        if not selected:
            return None
        if (selected.state or "").lower() == "ready":
            if selected.message in (None, "", "系统就绪", "数据库正常", "图像路径正常", "数据刷新正常"):
                return None
        return {
            "service": selected.name,
            "label": selected.label,
            "priority": selected.priority,
            "state": selected.state,
            "message": selected.message or "系统就绪",
            "data": selected.data,
            "updated_at": selected.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def get_simple_status(self, line_key: str | None = None, kind: str | None = None) -> dict[str, Any] | None:
        with self._status_lock:
            if line_key and kind:
                services = list(self._service_status.get((line_key, kind), {}).values())
                return self._select_simple(services)
            if line_key:
                for (key, view_kind), services_map in self._service_status.items():
                    if key == line_key and (kind is None or view_kind == kind):
                        result = self._select_simple(list(services_map.values()))
                        if result:
                            result["kind"] = view_kind
                            return result
                return None
            for (_, view_kind), services_map in self._service_status.items():
                result = self._select_simple(list(services_map.values()))
                if result:
                    result["kind"] = view_kind
                    return result
        return None

    def get_service_logs(
        self,
        *,
        line_key: str,
        kind: str,
        service: str,
        cursor: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        with self._status_lock:
            log_map = self._service_logs.get((line_key, kind), {})
            if service != "all":
                buffer = log_map.get(service, deque())
                items = [item for item in buffer if item.log_id > cursor]
                if cursor <= 0:
                    items = list(buffer)[-max(1, min(limit, 500)) :]
                if limit > 0:
                    items = items[-limit:]
                next_cursor = items[-1].log_id if items else cursor
                return {
                    "items": [
                        {
                            "service": item.service,
                            "id": item.log_id,
                            "time": item.time,
                            "level": item.level,
                            "message": item.message,
                            "data": item.data,
                        }
                        for item in items
                    ],
                    "cursor": next_cursor,
                }
            combined: list[ServiceLogEntry] = []
            for buffer in log_map.values():
                combined.extend([item for item in buffer if item.log_id > cursor])
            combined.sort(key=lambda item: (item.time, item.log_id))
            if limit > 0:
                combined = combined[-limit:]
            next_cursor = combined[-1].log_id if combined else cursor
            return {
                "items": [
                    {
                        "service": item.service,
                        "id": item.log_id,
                        "time": item.time,
                        "level": item.level,
                        "message": item.message,
                        "data": item.data,
                    }
                    for item in combined
                ],
                "cursor": next_cursor,
            }

    def clear_service_logs(self, *, line_key: str, kind: str, service: str) -> None:
        with self._status_lock:
            log_map = self._service_logs.get((line_key, kind))
            if not log_map:
                return
            if service == "all":
                log_map.clear()
                self._service_log_last_id.pop((line_key, kind), None)
                return
            log_map.pop(service, None)
            last_map = self._service_log_last_id.get((line_key, kind))
            if last_map:
                last_map.pop(service, None)


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


def _ensure_nginx_running() -> None:
    if sys.platform != "win32":
        if sys.platform == "darwin":
            nginx_conf_candidates = [
                Path("/opt/homebrew/etc/nginx/nginx.conf"),
                Path("/usr/local/etc/nginx/nginx.conf"),
            ]
            nginx_conf_path = next((p for p in nginx_conf_candidates if p.exists()), None)
            if not nginx_conf_path:
                logger.warning(
                    "Nginx config not found in Homebrew paths. Run apply_nginx.sh first."
                )
                return

            nginx_running = False
            for proc in psutil.process_iter(['name']):
                if proc.info['name'] == 'nginx':
                    nginx_running = True
                    break

            if not nginx_running:
                logger.info("Nginx is not running. Attempting to start Nginx using run_nginx.sh...")
                run_nginx_sh_path = REPO_ROOT.parent / "run_nginx.sh"
                try:
                    subprocess.Popen(["/bin/bash", str(run_nginx_sh_path)])
                    logger.info("Executed run_nginx.sh. Please verify Nginx started correctly.")
                except Exception as e:
                    logger.error("Failed to start Nginx using run_nginx.sh: %s", e)
                    raise SystemExit(1)
            return
        return

    nginx_conf_path = REPO_ROOT.parent / "plugins" / "platforms" / "windows" / "nginx" / "conf" / "nginx.conf"
    if not nginx_conf_path.exists():
        logger.error("Nginx configuration file not found: %s", nginx_conf_path)
        raise FileNotFoundError(f"Nginx configuration file not found: {nginx_conf_path}")

    nginx_running = False
    for proc in psutil.process_iter(['name']):
        if proc.info['name'] == 'nginx.exe':
            nginx_running = True
            break

    if not nginx_running:
        logger.info("Nginx is not running. Attempting to start Nginx using run_nginx.bat...")
        run_nginx_bat_path = REPO_ROOT.parent / "run_nginx.bat"
        try:
            # 使用 start 命令在新的窗口中运行批处理文件，避免阻塞
            subprocess.Popen(f'start "" "{run_nginx_bat_path}"', shell=True)
            logger.info("Executed run_nginx.bat. Please verify Nginx started correctly.")
        except Exception as e:
            logger.error("Failed to start Nginx using run_nginx.bat: %s", e)
            raise SystemExit(1)



def main() -> None:
    logging.basicConfig(level=logging.INFO)
    _ensure_nginx_running()
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
    lines: list[dict[str, Any]] = config.get("lines") or []
    views: dict[str, Any] = config.get("views") or {}
    log_defaults = config.get("log") or {}
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
        if line_key:
            candidate = CURRENT_DIR / "generated" / line_key / "DefectClass.json"
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
            view_payload = dict(view_config) if isinstance(view_config, dict) else {}
            view_log = _filter_log_config(view_payload.pop("log", None))
            line_payload = dict(line)
            base_log = _filter_log_config(log_defaults)
            line_log = _filter_log_config(line_payload.get("log"))
            effective_log = _merge_dict(dict(base_log), line_log)
            effective_log = _merge_dict(effective_log, view_log)
            if effective_log:
                line_payload["log"] = effective_log
            override_path = CURRENT_DIR / "generated" / line_key / view_key / "server.json"
            config_path = build_config_for_line(
                line_payload,
                template,
                view_name=view_key,
                view_overrides=view_payload,
                override_path=override_path,
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
    config_center_log = _filter_log_config(log_defaults)
    config_center_root = log_defaults.get("config_center_root_dir") if isinstance(log_defaults, dict) else None
    if config_center_root:
        config_center_log["root_dir"] = config_center_root
    config_center_name = (
        str(log_defaults.get("config_center_name") or "config_center")
        if isinstance(log_defaults, dict)
        else "config_center"
    )
    _configure_logging(
        "config_center",
        line_key="config_center",
        line_kind="center",
        log_overrides=config_center_log,
        server_name=config_center_name,
        default_root=REPO_ROOT.parent / "logs" / "config_center_log",
    )
    config_app = create_app(manager)
    uvicorn.run(config_app, host="0.0.0.0", port=8119, reload=False, workers=1)


if __name__ == "__main__":
    mp.freeze_support()
    main()
