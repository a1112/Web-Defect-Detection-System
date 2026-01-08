from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "configs"
CURRENT_ROOT = CONFIG_DIR / "current"
TEMPLATE_ROOT = CONFIG_DIR / "template"
GENERATED_ROOT = CURRENT_ROOT / "generated"


def _ensure_current_root() -> Path:
    CURRENT_ROOT.mkdir(parents=True, exist_ok=True)
    TEMPLATE_ROOT.mkdir(parents=True, exist_ok=True)
    for name in ("server.json", "map.json", "DefectClass.json"):
        target = CURRENT_ROOT / name
        if target.exists():
            continue
        source = TEMPLATE_ROOT / name
        if source.exists():
            shutil.copy2(source, target)
    return CURRENT_ROOT


def resolve_net_table_dir(hostname: str | None = None) -> Path:
    return _ensure_current_root()


def load_map_config(hostname: str | None = None) -> dict[str, Any]:
    root = resolve_net_table_dir(hostname)
    map_path = root / "map.json"
    defaults: dict[str, Any] = {}
    views: dict[str, Any] = {}
    if map_path.exists() and map_path.stat().st_size > 0:
        payload = json.loads(map_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            lines = payload
        elif isinstance(payload, dict):
            defaults = payload.get("defaults") or {}
            views = payload.get("views") or {}
            lines = payload.get("lines") or payload.get("items") or payload.get("data") or []
        else:
            lines = []
    else:
        lines = []
    return {"root": root, "lines": lines, "defaults": defaults, "views": views}


def load_map_payload(hostname: str | None = None) -> tuple[Path, dict[str, Any]]:
    root = resolve_net_table_dir(hostname)
    map_path = root / "map.json"
    defaults: dict[str, Any] = {}
    views: dict[str, Any] = {}
    if map_path.exists() and map_path.stat().st_size > 0:
        payload = json.loads(map_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return root, {"defaults": {}, "views": {}, "lines": payload}
        if isinstance(payload, dict):
            defaults = payload.get("defaults") or {}
            views = payload.get("views") or {}
            lines = payload.get("lines") or payload.get("items") or payload.get("data") or []
            return root, {"defaults": defaults, "views": views, "lines": lines}
    return root, {"defaults": defaults, "views": views, "lines": []}


def save_map_payload(payload: dict[str, Any], hostname: str | None = None) -> Path:
    root = resolve_net_table_dir(hostname)
    map_path = root / "map.json"
    payload = payload or {}
    defaults = payload.get("defaults") or {}
    views = payload.get("views") or {}
    lines = payload.get("lines") or []
    if not isinstance(lines, list):
        raise ValueError("lines must be a list")
    stored = {"defaults": defaults, "views": views, "lines": lines}
    map_path.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
    return map_path


def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _merge_dict(dict(base[key]), value)
        else:
            base[key] = value
    return base


def _apply_ip_format(value: Any, ip: str | None) -> Any:
    if ip is None or not isinstance(value, str):
        return value
    if "{ip}" in value:
        return value.format(ip=ip)
    if "127.0.0.1" in value:
        return value.replace("127.0.0.1", ip)
    return value


def build_config_for_line(
    line: dict[str, Any],
    template_path: Path,
    defaults: dict[str, Any] | None = None,
    view_name: str | None = None,
    view_overrides: dict[str, Any] | None = None,
) -> Path:
    payload = json.loads(template_path.read_text(encoding="utf-8"))
    defaults = defaults or {}
    payload = _merge_dict(payload, defaults)

    database = payload.get("database", {}) if isinstance(payload.get("database"), dict) else {}
    images = payload.get("images", {}) if isinstance(payload.get("images"), dict) else {}

    line_db = line.get("db") or line.get("database") or {}
    line_images = line.get("images") or line.get("image") or {}
    if isinstance(line_db, dict):
        database = _merge_dict(database, line_db)
    if isinstance(line_images, dict):
        images = _merge_dict(images, line_images)
    if isinstance(view_overrides, dict):
        images = _merge_dict(images, view_overrides)
    if view_name:
        images["default_view"] = view_name

    ip = line.get("ip") or database.get("host")
    if ip and not database.get("host"):
        database["host"] = ip
    if ip and isinstance(database.get("host"), str):
        database["host"] = _apply_ip_format(database["host"], ip)
    images = {key: _apply_ip_format(value, ip) for key, value in images.items()}

    payload["database"] = database
    payload["images"] = images

    line_name = str(line.get("name") or "line")
    safe_name = line_name.replace("/", "_").replace("\\", "_")
    view_suffix = view_name.replace("/", "_").replace("\\", "_") if view_name else "default"
    target_dir = GENERATED_ROOT / safe_name / view_suffix
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / template_path.name
    target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target_path


def get_api_list(hostname: str | None = None) -> list[dict[str, Any]]:
    config = load_map_config(hostname)
    lines = config.get("lines") or []
    views = config.get("views") or {}
    items: list[dict[str, Any]] = []
    for line in lines:
        name = str(line.get("name") or "")
        key = str(line.get("key") or name)
        if not key:
            continue
        encoded = quote(key, safe="")
        profile = line.get("profile") or line.get("api_profile") or "default"
        view_keys = list(views.keys()) if isinstance(views, dict) and views else ["2D"]
        view_payloads = []
        for view_key in view_keys:
            suffix = "api" if view_key in ("2D", "default") else f"{view_key}--api"
            view_payloads.append(
                {
                    "view": view_key,
                    "path": f"/{suffix}/{encoded}",
                    "profile": profile,
                }
            )
        items.append(
            {
                "key": key,
                "name": name,
                "mode": line.get("mode") or "direct",
                "path": f"/api/{encoded}",
                "profile": profile,
                "port": line.get("port") or line.get("listen_port"),
                "ip": line.get("ip"),
                "views": view_payloads,
            }
        )
    return items
