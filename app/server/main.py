from __future__ import annotations

import argparse
import os
import sys
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime
from threading import Event, Thread

# Ensure repository root is on sys.path before importing app.*
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, text
import requests

from app.server import deps
from app.server.api import defects, health, images, steels, meta, net, admin
from app.server.api.dependencies import get_image_service
from app.server.config.settings import ENV_CONFIG_KEY, ensure_config_file
from app.server.rbac.manager import bootstrap_management
from app.server.db.models.ncdplate import Steelrecord

logger = logging.getLogger(__name__)

API_VERSION = "0.1.0"
CONFIG_CENTER_URL_ENV = "DEFECT_CONFIG_CENTER_URL"
LINE_KEY_ENV = "DEFECT_LINE_KEY"
LINE_NAME_ENV = "DEFECT_LINE_NAME"
LINE_KIND_ENV = "DEFECT_LINE_KIND"
LINE_HOST_ENV = "DEFECT_LINE_HOST"
LINE_PORT_ENV = "DEFECT_LINE_PORT"
HEARTBEAT_INTERVAL_ENV = "DEFECT_CONFIG_HEARTBEAT_INTERVAL_SECONDS"


def _resolve_status_url(base_url: str) -> str:
    cleaned = base_url.rstrip("/")
    if cleaned.endswith("/config"):
        return f"{cleaned}/api_status"
    return f"{cleaned}/config/api_status"


def _parse_int(value: str | None) -> int | None:
    if not value:
        return None
    if value.isdigit():
        return int(value)
    return None


def _collect_status_payload(line_key: str, line_name: str | None, line_kind: str | None) -> dict[str, object]:
    latest_timestamp = None
    latest_age_seconds = None
    online = True
    try:
        with deps.get_main_db() as session:
            latest = session.query(func.max(Steelrecord.detectTime)).scalar()
        if latest is not None:
            latest_timestamp = latest.isoformat()
            latest_age_seconds = max(0, int((datetime.utcnow() - latest).total_seconds()))
    except Exception:
        logger.exception("Failed to query latest Steelrecord for status push.")
        online = False
    payload: dict[str, object] = {
        "key": line_key,
        "name": line_name,
        "kind": line_kind or "default",
        "host": os.getenv(LINE_HOST_ENV),
        "port": _parse_int(os.getenv(LINE_PORT_ENV)),
        "pid": os.getpid(),
        "online": online,
        "latest_timestamp": latest_timestamp,
        "latest_age_seconds": latest_age_seconds,
    }
    return payload


def _status_reporter(stop_event: Event, base_url: str, line_key: str, line_name: str | None, line_kind: str | None) -> None:
    interval = _parse_int(os.getenv(HEARTBEAT_INTERVAL_ENV)) or 15
    status_url = _resolve_status_url(base_url)
    while not stop_event.is_set():
        payload = _collect_status_payload(line_key, line_name, line_kind)
        try:
            requests.post(status_url, json=payload, timeout=5)
        except Exception:
            logger.exception("Failed to post status update to config center: %s", status_url)
        stop_event.wait(interval)


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """应用生命周期管理：启动时预热数据库连接。"""
    try:
        with deps.get_main_db() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Failed to warm up main database connection.")

    try:
        settings = deps.get_settings()
        with deps.get_management_db() as session:
            bootstrap_management(settings, session)
    except Exception:
        logger.exception("Failed to initialize management database.")

    try:
        get_image_service().start_background_workers()
    except Exception:
        logger.exception("Failed to start background cache workers.")
    status_stop: Event | None = None
    status_thread: Thread | None = None
    config_center_url = os.getenv(CONFIG_CENTER_URL_ENV, "").strip()
    line_key = os.getenv(LINE_KEY_ENV) or os.getenv(LINE_NAME_ENV)
    line_name = os.getenv(LINE_NAME_ENV)
    line_kind = os.getenv(LINE_KIND_ENV)
    if config_center_url and line_key:
        status_stop = Event()
        status_thread = Thread(
            target=_status_reporter,
            args=(status_stop, config_center_url, line_key, line_name, line_kind),
            daemon=True,
        )
        status_thread.start()
    yield
    try:
        get_image_service().stop_background_workers()
    except Exception:
        logger.exception("Failed to stop background cache workers.")
    if status_stop:
        status_stop.set()
    if status_thread:
        status_thread.join(timeout=2)


app = FastAPI(title="Web Defect Detection API", version=API_VERSION, lifespan=app_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


# Register API routers
app.include_router(health.router)
app.include_router(steels.router)
app.include_router(defects.router)
app.include_router(images.router)
app.include_router(meta.router)
app.include_router(net.router)
app.include_router(admin.router, prefix="/api")
app.include_router(admin.router, prefix="/config")


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="Web Defect Detection API server")
    parser.add_argument("--config", help="Path to JSON config file")
    parser.add_argument("--host", default=os.getenv("BKJC_API_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("BKJC_API_PORT", "8120")))
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.getenv("BKJC_API_WORKERS", "4")),
        help="Number of Uvicorn worker processes (production only; incompatible with --reload).",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=os.getenv("BKJC_API_RELOAD", "true").lower() == "true",
        help="Enable auto-reload (development only)",
    )
    parser.add_argument("--ssl-certfile", default="", help="Path to SSL certificate (PEM)")
    parser.add_argument("--ssl-keyfile", default=None, help="Path to SSL private key (PEM)")
    parser.add_argument(
        "--test_data",
        action="store_true",
        help="Use TestData as data source (SQLite + local images).",
    )
    args = parser.parse_args()

    if args.config:
        os.environ[ENV_CONFIG_KEY] = str(Path(args.config).resolve())

    ensure_config_file(args.config)

    if args.test_data:
        testdata_dir = (REPO_ROOT / "TestData").resolve()
        _ensure_testdata_dir(testdata_dir)
        os.environ[TEST_MODE_ENV] = "true"
        os.environ[TESTDATA_DIR_ENV] = str(testdata_dir)

    if args.reload and args.workers != 1:
        logger.warning(
            "Reload mode is enabled; forcing workers=1 because multiple workers "
            "are not supported together with auto-reload."
        )
        args.workers = 1

    ssl_cert = args.ssl_certfile or os.getenv(SSL_CERT_ENV)
    ssl_key = args.ssl_keyfile or os.getenv(SSL_KEY_ENV)
    ssl_kwargs = {}
    if ssl_cert or ssl_key:
        if bool(ssl_cert) ^ bool(ssl_key):
            raise RuntimeError(
                "Both SSL certificate and key must be provided. "
                f"Pass --ssl-certfile/--ssl-keyfile or set {SSL_CERT_ENV}/{SSL_KEY_ENV}."
            )
        ssl_kwargs = {"ssl_certfile": ssl_cert, "ssl_keyfile": ssl_key}
        logger.info("HTTPS enabled with SSL cert/key.")
    else:
        logger.info("No SSL cert/key provided; serving over HTTP.")
    uvicorn.run(
        "app.server.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers,
        **ssl_kwargs,
    )
