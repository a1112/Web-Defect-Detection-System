from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parents[2]
NET_TABLE_ROOT = REPO_ROOT / "configs" / "net_tabel"
DATA_ROOT = NET_TABLE_ROOT / "DATA"
DEFAULT_ROOT = NET_TABLE_ROOT / "DEFAULT"
GENERATED_ROOT = NET_TABLE_ROOT / "generated"


def resolve_net_table_dir(hostname: str | None = None) -> Path:
    name = hostname or socket.gethostname()
    candidate = DATA_ROOT / name
    if candidate.exists():
        return candidate
    return DEFAULT_ROOT


def _iter_line_dirs(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return [item for item in root.iterdir() if item.is_dir()]


def _generate_lines_from_dirs(root: Path) -> list[dict[str, Any]]:
    base_port = 8200
    lines: list[dict[str, Any]] = []
    for idx, folder in enumerate(sorted(_iter_line_dirs(root), key=lambda item: item.name)):
        lines.append(
            {
                "name": folder.name,
                "mode": "direct",
                "ip": None,
                "port": base_port + idx,
            }
        )
    return lines


def load_map_config(hostname: str | None = None) -> dict[str, Any]:
    root = resolve_net_table_dir(hostname)
    map_path = root / "map.json"
    defaults: dict[str, Any] = {}
    if map_path.exists() and map_path.stat().st_size > 0:
        payload = json.loads(map_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            lines = payload
        elif isinstance(payload, dict):
            defaults = payload.get("defaults") or {}
            lines = payload.get("lines") or payload.get("items") or payload.get("data") or []
        else:
            lines = []
    else:
        lines = _generate_lines_from_dirs(root)
    if not lines and root != DEFAULT_ROOT:
        fallback_path = DEFAULT_ROOT / "map.json"
        if fallback_path.exists() and fallback_path.stat().st_size > 0:
            payload = json.loads(fallback_path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                lines = payload
            elif isinstance(payload, dict):
                defaults = payload.get("defaults") or {}
                lines = payload.get("lines") or payload.get("items") or payload.get("data") or []
            root = DEFAULT_ROOT
        else:
            lines = _generate_lines_from_dirs(DEFAULT_ROOT)
            root = DEFAULT_ROOT
    if not lines and root == DEFAULT_ROOT:
        data_dirs = [item for item in _iter_line_dirs(DATA_ROOT) if item.is_dir()]
        if data_dirs:
            fallback_root = sorted(data_dirs, key=lambda item: item.name)[0]
            lines = _generate_lines_from_dirs(fallback_root)
            root = fallback_root
    return {"root": root, "lines": lines, "defaults": defaults}


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
    target_dir = GENERATED_ROOT / safe_name
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / template_path.name
    target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target_path


def get_api_list(hostname: str | None = None) -> list[dict[str, Any]]:
    config = load_map_config(hostname)
    lines = config.get("lines") or []
    items: list[dict[str, Any]] = []
    for line in lines:
        name = str(line.get("name") or "")
        if not name:
            continue
        encoded = quote(name, safe="")
        profile = line.get("profile") or line.get("api_profile") or "default"
        path_suffix = "small-api" if profile == "small" else "api"
        items.append(
            {
                "name": name,
                "mode": line.get("mode") or "direct",
                "path": f"/{encoded}/{path_suffix}",
                "profile": profile,
                "port": line.get("port") or line.get("listen_port"),
                "ip": line.get("ip"),
            }
        )
    return items
