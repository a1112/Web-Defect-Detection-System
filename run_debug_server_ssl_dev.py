#!/usr/bin/env python
"""
Launcher for the Web Defect Detection API in "test mode" over HTTPS.

Ports:
  - 2D: 8220
  - SMALL: 8230
"""

from __future__ import annotations

import multiprocessing as mp
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent

CONFIG_NEEDS = [
    ("DEFECT_DEBUG_TEST_SSL_2D", REPO_ROOT / "configs" / "server.json", 8220),
    ("DEFECT_DEBUG_TEST_SSL_SMALL", REPO_ROOT / "configs" / "server_small.json", 8230),
]

DEFAULT_CERT = REPO_ROOT / "certs" / "bkvision.online" / "bkvision.online.crt"
DEFAULT_KEY = REPO_ROOT / "certs" / "bkvision.online" / "bkvision.online.key"


def ensure_testdata() -> Path:
    testdata_dir = (REPO_ROOT / "TestData").resolve()
    required = [
        testdata_dir / "DataBase",
        testdata_dir / "Image",
    ]
    missing = [p for p in required if not p.exists()]
    if missing:
        for p in missing:
            print(f"[error] Missing TestData path: {p}")
        raise SystemExit(1)
    return testdata_dir


def ensure_configs() -> None:
    missing = [cfg for _, cfg, _ in CONFIG_NEEDS if not cfg.exists()]
    if not missing:
        return
    for cfg in missing:
        print(f"[error] Required config not found: {cfg}")
    raise SystemExit(1)


def resolve_ssl_files() -> tuple[Path, Path]:
    cert_env = os.getenv("DEFECT_SSL_CERT") or ""
    key_env = os.getenv("DEFECT_SSL_KEY") or ""
    cert = Path(cert_env).resolve() if cert_env else DEFAULT_CERT.resolve()
    key = Path(key_env).resolve() if key_env else DEFAULT_KEY.resolve()
    if not cert.exists() or not key.exists():
        print("[error] SSL cert/key not found.")
        print(f"[error] cert: {cert}")
        print(f"[error] key : {key}")
        print("[hint] Set DEFECT_SSL_CERT / DEFECT_SSL_KEY env vars, or add certs under ./certs/.")
        raise SystemExit(1)
    return cert, key


def launch_server(title: str, config_path: Path, port: int, testdata_dir: Path, cert: Path, key: Path) -> None:
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
        "--ssl-certfile",
        str(cert),
        "--ssl-keyfile",
        str(key),
    ]
    env = os.environ.copy()
    env["DEFECT_TEST_MODE"] = "true"
    env["DEFECT_TESTDATA_DIR"] = str(testdata_dir)
    env["BKJC_API_RELOAD"] = "true"
    print(f"[info] ({title}) Launching: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=REPO_ROOT, env=env, check=False)


def main() -> None:
    print("[info] Starting Web Defect Detection API in test mode (HTTPS)...")
    ensure_configs()
    testdata_dir = ensure_testdata()
    cert, key = resolve_ssl_files()

    processes: list[mp.Process] = []
    for title, config_path, port in CONFIG_NEEDS:
        process = mp.Process(
            target=launch_server,
            args=(title, config_path, port, testdata_dir, cert, key),
            daemon=False,
        )
        process.start()
        processes.append(process)

    print("[info] Test-mode HTTPS servers running. Press Ctrl+C to stop.")
    try:
        for process in processes:
            process.join()
    except KeyboardInterrupt:
        print("\n[info] Stopping test-mode HTTPS servers...")
        for process in processes:
            if process.is_alive():
                process.terminate()
    finally:
        for process in processes:
            process.join()
    print("[info] All test-mode HTTPS servers stopped.")


if __name__ == "__main__":
    mp.freeze_support()
    main()
