from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import multiprocessing as mp
from pathlib import Path
import re
import json
from typing import Any

import uvicorn

from app.server.config.settings import ENV_CONFIG_KEY
from app.server.net_table import load_map_config, build_config_for_line

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = REPO_ROOT / "configs"


def _resolve_template(profile: str | None) -> Path:
    name = "server_small.json" if profile == "small" else "server.json"
    return CONFIG_DIR / name


def _line_port(line: dict[str, Any], fallback: int) -> int:
    for key in ("port", "listen_port", "service_port"):
        value = line.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return fallback


def _line_host(line: dict[str, Any]) -> str:
    host = line.get("listen_host") or line.get("host") or "0.0.0.0"
    return str(host)


def _run_uvicorn(
    config_path: Path,
    host: str,
    port: int,
    defect_class_path: Path | None,
    line_name: str,
) -> None:
    _configure_logging(line_name)
    _log_database_url(config_path, line_name)
    os.environ[ENV_CONFIG_KEY] = str(config_path.resolve())
    if defect_class_path:
        os.environ["DEFECT_CLASS_PATH"] = str(defect_class_path.resolve())
    uvicorn.run(
        "app.server.main:app",
        host=host,
        port=port,
        reload=False,
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


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Net table multi-line server launcher")
    parser.add_argument("--hostname", default=None, help="Override hostname for net_tabel lookup")
    args = parser.parse_args()

    config = load_map_config(args.hostname)
    defaults = config.get("defaults") or {}
    root = config.get("root")
    lines: list[dict[str, Any]] = config.get("lines") or []
    if not lines:
        raise RuntimeError("No net_tabel lines found; check configs/net_tabel/DATA/<hostname>/map.json")

    processes: list[mp.Process] = []
    base_port = 8200
    for idx, line in enumerate(lines):
        mode = (line.get("mode") or "direct").lower()
        if mode != "direct":
            continue
        profile = line.get("profile") or line.get("api_profile")
        template = _resolve_template(profile)
        if not template.exists():
            raise FileNotFoundError(f"Template config not found: {template}")
        config_path = build_config_for_line(line, template, defaults=defaults)
        port = _line_port(line, base_port + idx)
        host = _line_host(line)
        logger.info("Starting line '%s' on %s:%s with %s", line.get("name"), host, port, template.name)
        line_name = str(line.get("name") or "")
        defect_class_path = None
        if root and line_name:
            candidate = Path(root) / line_name / "DefectClass.json"
            if candidate.exists():
                defect_class_path = candidate
        if defect_class_path is None:
            fallback = REPO_ROOT / "configs" / "net_tabel" / "DEFAULT" / "本地测试数据" / "DefectClass.json"
            if fallback.exists():
                defect_class_path = fallback
        process = mp.Process(
            target=_run_uvicorn,
            args=(config_path, host, port, defect_class_path, line_name),
            daemon=False,
            name=line_name or None,
        )
        process.start()
        processes.append(process)

    for process in processes:
        process.join()


if __name__ == "__main__":
    mp.freeze_support()
    main()
