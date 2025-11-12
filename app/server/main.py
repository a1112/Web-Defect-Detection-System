from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from functools import lru_cache
from typing import Optional

import logging

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.server import deps
from app.server.schemas import DefectResponse, SteelListResponse
from app.server.services.defect_service import DefectService
from app.server.services.image_service import ImageService
from app.server.services.steel_service import SteelService

from app.server.config.settings import ENV_CONFIG_KEY, ensure_config_file

logger = logging.getLogger(__name__)

app = FastAPI(title="Web Defect Detection API", version="0.1.0")

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


def _resolve_ui_index() -> Path | None:
    for name in ("DefectWebUi.html", "index.html"):
        candidate = UI_BUILD_DIR / name
        if candidate.exists():
            return candidate
    return None


if UI_BUILD_DIR.exists():
    app.mount(
        "/ui",
        StaticFiles(directory=str(UI_BUILD_DIR), html=True),
        name="defect-web-ui",
    )

    @app.get("/", include_in_schema=False)
    async def serve_ui_root():
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


def get_steel_service() -> SteelService:
    return SteelService(deps.get_dbm())


@lru_cache()
def get_defect_service() -> DefectService:
    return DefectService(deps.get_dbm())


@lru_cache()
def get_image_service() -> ImageService:
    return ImageService(deps.get_settings(), get_defect_service())


@app.get("/health")
def healthcheck():
    return {"status": "ok"}


@app.on_event("startup")
def init_app():
    # Establish database connection during startup so first request is fast
    deps.get_dbm()


@app.get("/api/steels", response_model=SteelListResponse)
def api_list_steels(
    limit: int = Query(20, ge=1, le=500),
    defect_only: bool = False,
    start_seq: Optional[int] = Query(default=None, description="Start seqNo (exclusive)"),
order: str = Query(default="desc", pattern="^(asc|desc)$"),
    service: SteelService = Depends(get_steel_service),
):
    desc = order != "asc"
    return service.list_recent(limit=limit, defect_only=defect_only, start_seq=start_seq, desc=desc)


@app.get("/api/steels/date", response_model=SteelListResponse)
def api_list_steels_by_date(
    start: datetime = Query(..., description="Start datetime (inclusive)"),
    end: datetime = Query(..., description="End datetime (inclusive)"),
    service: SteelService = Depends(get_steel_service),
):
    return service.by_date(start=start, end=end)


@app.get("/api/steels/steel-no/{steel_no}", response_model=SteelListResponse)
def api_steel_by_no(steel_no: str, service: SteelService = Depends(get_steel_service)):
    return service.by_steel_no(steel_no)


@app.get("/api/steels/id/{steel_id}", response_model=SteelListResponse)
def api_steel_by_id(steel_id: int, service: SteelService = Depends(get_steel_service)):
    return service.by_id(steel_id)


@app.get("/api/steels/seq/{seq_no}", response_model=SteelListResponse)
def api_steel_by_seq(seq_no: int, service: SteelService = Depends(get_steel_service)):
    return service.by_seq(seq_no)


@app.get("/api/defects/{seq_no}", response_model=DefectResponse)
def api_defects(
    seq_no: int,
surface: Optional[str] = Query(default=None, pattern="^(top|bottom)$"),
    service: DefectService = Depends(get_defect_service),
):
    return service.defects_by_seq(seq_no, surface=surface)


def _image_media_type(fmt: str) -> str:
    return f"image/{fmt.lower()}"


@app.get("/api/images/frame")
def api_frame_image(
surface: str = Query(..., pattern="^(top|bottom)$"),
    seq_no: int = Query(...),
    image_index: int = Query(..., ge=0),
    width: Optional[int] = Query(default=None, ge=1, le=8192),
    height: Optional[int] = Query(default=None, ge=1, le=8192),
    view: Optional[str] = Query(default=None),
    fmt: str = Query(default="JPEG"),
    service: ImageService = Depends(get_image_service),
):
    try:
        payload = service.get_frame(
            surface=surface,
            seq_no=seq_no,
            image_index=image_index,
            view=view,
            width=width,
            height=height,
            fmt=fmt,
        )
        return Response(content=payload, media_type=_image_media_type(fmt))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/images/defect/{defect_id}")
def api_defect_crop(
    defect_id: int,
surface: str = Query(..., pattern="^(top|bottom)$"),
    expand: int = Query(default=0, ge=0, le=512),
    width: Optional[int] = Query(default=None, ge=1, le=4096),
    height: Optional[int] = Query(default=None, ge=1, le=4096),
    fmt: str = Query(default="JPEG"),
    service: ImageService = Depends(get_image_service),
):
    try:
        data, defect = service.crop_defect(
            surface=surface,
            defect_id=defect_id,
            expand=expand,
            width=width,
            height=height,
            fmt=fmt,
        )
        headers = {
            "X-Seq-No": str(defect.seq_no),
            "X-Image-Index": str(defect.image_index or 0),
            "X-Camera-Id": str(defect.camera_id),
        }
        return Response(content=data, media_type=_image_media_type(fmt), headers=headers)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/images/crop")
def api_custom_crop(
surface: str = Query(..., pattern="^(top|bottom)$"),
    seq_no: int = Query(...),
    image_index: int = Query(...),
    x: int = Query(..., ge=0),
    y: int = Query(..., ge=0),
    w: int = Query(..., ge=1),
    h: int = Query(..., ge=1),
    expand: int = Query(default=0, ge=0, le=512),
    width: Optional[int] = Query(default=None, ge=1, le=4096),
    height: Optional[int] = Query(default=None, ge=1, le=4096),
    fmt: str = Query(default="JPEG"),
    service: ImageService = Depends(get_image_service),
):
    try:
        payload = service.crop_custom(
            surface=surface,
            seq_no=seq_no,
            image_index=image_index,
            x=x,
            y=y,
            w=w,
            h=h,
            expand=expand,
            width=width,
            height=height,
            fmt=fmt,
        )
        return Response(content=payload, media_type=_image_media_type(fmt))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/images/mosaic")
def api_mosaic_image(
surface: str = Query(..., pattern="^(top|bottom)$"),
    seq_no: int = Query(...),
    view: Optional[str] = Query(default=None),
    limit: Optional[int] = Query(default=None, ge=1, le=10000),
    skip: int = Query(default=0, ge=0),
    stride: int = Query(default=1, ge=1),
    width: Optional[int] = Query(default=None, ge=1),
    height: Optional[int] = Query(default=None, ge=1),
    fmt: str = Query(default="JPEG"),
    service: ImageService = Depends(get_image_service),
):
    try:
        payload = service.get_mosaic(
            surface=surface,
            seq_no=seq_no,
            view=view,
            limit=limit,
            skip=skip,
            stride=stride,
            width=width,
            height=height,
            fmt=fmt,
        )
        return Response(content=payload, media_type=_image_media_type(fmt))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/images/tile")
def api_tile_image(
    surface: str = Query(..., pattern="^(top|bottom)$"),
    seq_no: int = Query(...),
    view: Optional[str] = Query(default=None),
    level: int = Query(default=0, ge=0, le=8),
    tile_x: int = Query(..., ge=0),
    tile_y: int = Query(..., ge=0),
    tile_size: int = Query(default=512, ge=64, le=2048),
    fmt: str = Query(default="JPEG"),
    service: ImageService = Depends(get_image_service),
):
    try:
        payload = service.get_tile(
            surface=surface,
            seq_no=seq_no,
            view=view,
            level=level,
            tile_x=tile_x,
            tile_y=tile_y,
            tile_size=tile_size,
            fmt=fmt,
        )
        headers = {
            "X-Tile-Level": str(level),
            "X-Tile-X": str(tile_x),
            "X-Tile-Y": str(tile_y),
            "X-Tile-Size": str(tile_size),
        }
        return Response(content=payload, media_type=_image_media_type(fmt), headers=headers)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="Web Defect Detection API server")
    parser.add_argument("--config", help="Path to JSON config file")
    parser.add_argument("--host", default=os.getenv("BKJC_API_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("BKJC_API_PORT", "8000")))
    parser.add_argument(
        "--reload",
        action="store_true",
        default=os.getenv("BKJC_API_RELOAD", "false").lower() == "true",
        help="Enable auto-reload (development only)",
    )
    parser.add_argument("--ssl-certfile",default="./certs/server.crt", help="Path to SSL certificate (PEM)")
    parser.add_argument("--ssl-keyfile",default="./certs/server.key", help="Path to SSL private key (PEM)")
    args = parser.parse_args()

    if args.config:
        os.environ[ENV_CONFIG_KEY] = str(Path(args.config).resolve())

    ensure_config_file(args.config)

    ssl_cert = args.ssl_certfile or os.getenv(SSL_CERT_ENV)
    ssl_key = args.ssl_keyfile or os.getenv(SSL_KEY_ENV)
    if bool(ssl_cert) ^ bool(ssl_key):
        raise RuntimeError(
            "Both SSL certificate and key must be provided. "
            f"Pass --ssl-certfile/--ssl-keyfile or set {SSL_CERT_ENV}/{SSL_KEY_ENV}."
        )
    uvicorn.run(
        "app.server.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        ssl_certfile=ssl_cert,
        ssl_keyfile=ssl_key,
    )
