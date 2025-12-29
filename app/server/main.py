from __future__ import annotations

import argparse
import os
import sys
import logging
from pathlib import Path
from contextlib import asynccontextmanager

# Ensure repository root is on sys.path before importing app.*
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from app.server import deps
from app.server.api import defects, health, images, steels, meta, net, admin
from app.server.api.dependencies import get_image_service
from app.server.config.settings import ENV_CONFIG_KEY, ensure_config_file
from app.server.rbac.manager import bootstrap_management

logger = logging.getLogger(__name__)

API_VERSION = "0.1.0"


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
    yield
    try:
        get_image_service().stop_background_workers()
    except Exception:
        logger.exception("Failed to stop background cache workers.")


app = FastAPI(title="Web Defect Detection API", version=API_VERSION, lifespan=app_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CoopCoepMiddleware(BaseHTTPMiddleware):
    """Ensure /ui responses can use SharedArrayBuffer by enabling cross-origin isolation."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path or ""
        if path == "/" or path.startswith("/ui"):
            response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
            response.headers.setdefault("Cross-Origin-Embedder-Policy", "require-corp")
            response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        return response


app.add_middleware(CoopCoepMiddleware)

UI_BUILD_ENV_KEY = "DEFECT_UI_BUILD_DIR"
DEFAULT_UI_BUILD_DIR = (
    REPO_ROOT
    / "app"
    / "ui"
    / "DefectWebUi"
    / "build"
    / "WebAssembly_Qt_6_10_0_multi_threaded-MinSizeRel"
)
UI_BUILD_DIR = Path(os.getenv(UI_BUILD_ENV_KEY, DEFAULT_UI_BUILD_DIR))
SSL_CERT_ENV = "DEFECT_SSL_CERT"
SSL_KEY_ENV = "DEFECT_SSL_KEY"
TEST_MODE_ENV = "DEFECT_TEST_MODE"
TESTDATA_DIR_ENV = "DEFECT_TESTDATA_DIR"


def _resolve_ui_index() -> Path | None:
    for name in ("DefectWebUi.html", "index.html"):
        candidate = UI_BUILD_DIR / name
        if candidate.exists():
            return candidate
    return None


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


if UI_BUILD_DIR.exists():
    app.mount(
        "/ui",
        StaticFiles(directory=str(UI_BUILD_DIR), html=True),
        name="defect-web-ui",
    )

    @app.get("/", include_in_schema=False)
    async def serve_ui_root():
        """提供前端静态页面入口文件。"""
        index_path = _resolve_ui_index()
        if not index_path:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Defect Web UI index not found inside "
                    f"{UI_BUILD_DIR}. Check your WASM build output."
                ),
            )
        return FileResponse(index_path)
else:
    logger.warning(
        "Defect Web UI build directory %s not found. "
        "Set %s to point at your Qt WASM output to enable the frontend.",
        UI_BUILD_DIR,
        UI_BUILD_ENV_KEY,
    )


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
