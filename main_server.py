from __future__ import annotations

import argparse
import logging
import os
import multiprocessing as mp
from pathlib import Path
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
) -> None:
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
            args=(config_path, host, port, defect_class_path),
            daemon=False,
        )
        process.start()
        processes.append(process)

    for process in processes:
        process.join()


if __name__ == "__main__":
    mp.freeze_support()
    main()
