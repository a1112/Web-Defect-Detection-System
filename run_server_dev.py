#!/usr/bin/env python
"""
Multiprocess launcher for the Web Defect Detection dev servers.

This mirrors run_server_dev.bat but keeps everything inside a single Python
script so it can be driven from terminals that prefer Python over batch files.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
CONFIG_NEEDS = [
    ("BKJC_API_DEV_2D", REPO_ROOT / "configs" / "server.json", 8120),
    ("BKJC_API_DEV_SMALL", REPO_ROOT / "configs" / "server_small.json", 8130),
]


def ensure_configs() -> None:
    missing = [cfg for _, cfg, _ in CONFIG_NEEDS if not cfg.exists()]
    if not missing:
        return

    for cfg in missing:
        print(f"[error] Required config not found: {cfg}")
    raise SystemExit(1)


def launch_server(title: str, config_path: Path, port: int) -> None:
    """Run a single FastAPI instance until it exits."""
    cmd = [
        sys.executable,
        "app/server/main.py",
        "--config",
        str(config_path),
        "--host",
        "0.0.0.0",
        "--port",
        str(port),
        "--reload",
    ]
    env = os.environ.copy()
    print(f"[info] ({title}) Launching: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=REPO_ROOT, env=env, check=False)


def main() -> None:
    print("[info] Starting Web Defect Detection API dev servers (Python launcher)...")
    ensure_configs()
    os.environ["BKJC_API_RELOAD"] = "true"
    processes: list[mp.Process] = []

    for title, config_path, port in CONFIG_NEEDS:
        process = mp.Process(target=launch_server, args=(title, config_path, port), daemon=False)
        process.start()
        processes.append(process)

    print("[info] Servers running. Press Ctrl+C to stop both instances.")
    try:
        for process in processes:
            process.join()
    except KeyboardInterrupt:
        print("\n[info] Stopping dev servers...")
        for process in processes:
            if process.is_alive():
                process.terminate()
    finally:
        for process in processes:
            process.join()
    print("[info] All dev servers stopped.")


if __name__ == "__main__":
    mp.freeze_support()
    main()
