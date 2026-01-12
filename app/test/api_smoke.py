import sys
import time
from typing import Any

import requests


HOST_URL = "http://127.0.0.1:80"
BASE_URL = f"{HOST_URL}/api"
TIMEOUT = 10


def _get_json(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{BASE_URL}{path}"
    resp = requests.get(url, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _get_bytes(path: str, params: dict[str, Any] | None = None) -> tuple[bytes, str]:
    url = f"{BASE_URL}{path}"
    resp = requests.get(url, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "")
    return resp.content, content_type


def _get_json_full(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    start = time.perf_counter()
    print("GET", url, "params=", params or {})
    resp = requests.get(url, params=params, timeout=TIMEOUT)
    elapsed_ms = (time.perf_counter() - start) * 1000
    status = f"[GREEN] {resp.status_code}" if resp.ok else f"[RED] {resp.status_code}"
    print("TIME", f"{elapsed_ms:.1f}ms", status, url)
    resp.raise_for_status()
    return resp.json()


def _get_bytes_full(url: str, params: dict[str, Any] | None = None) -> tuple[bytes, str]:
    start = time.perf_counter()
    print("GET", url, "params=", params or {})
    resp = requests.get(url, params=params, timeout=TIMEOUT)
    elapsed_ms = (time.perf_counter() - start) * 1000
    status = f"[GREEN] {resp.status_code}" if resp.ok else f"[RED] {resp.status_code}"
    print("TIME", f"{elapsed_ms:.1f}ms", status, url)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "")
    return resp.content, content_type


def _ws_base(base_url: str) -> str:
    if base_url.startswith("https://"):
        return base_url.replace("https://", "wss://", 1)
    return base_url.replace("http://", "ws://", 1)


def _ws_read_once(base_url: str, path: str) -> bool:
    try:
        from websocket import create_connection
    except Exception:
        print("websocket-client not installed; skip ws:", path)
        return True
    try:
        ws = create_connection(f"{_ws_base(base_url)}{path}", timeout=TIMEOUT)
        ws.settimeout(TIMEOUT)
        message = ws.recv()
        ws.close()
        print("ws message:", path, message)
        return True
    except Exception as exc:
        print("ws failed:", path, exc)
        return False


def _check_api_base(base_url: str, label: str) -> bool:
    try:
        health = _get_json_full(f"{base_url}/health")
        print("health:", label, health)
        return True
    except Exception as exc:
        print("health failed:", label, exc)
        return False


def _load_api_list() -> dict[str, Any] | None:
    try:
        return _get_json_full(f"{HOST_URL}/config/api_list")
    except Exception:
        try:
            return _get_json_full(f"{HOST_URL}/api_list")
        except Exception as exc:
            print("api_list not available:", exc)
            return None


def _collect_base_paths(api_list: dict[str, Any] | None) -> list[str]:
    base_paths: list[str] = []
    if not api_list:
        return ["/api"]
    items = api_list.get("items") or []
    for item in items:
        key = item.get("key")
        if isinstance(key, str) and key:
            base_paths.append(f"/api/{key}")
            small_path = item.get("small_path")
            if isinstance(small_path, str) and small_path:
                base_paths.append(f"{small_path}/{key}")
        path = item.get("path")
        if isinstance(path, str) and path:
            base_paths.append(path)
        for view in item.get("views") or []:
            view_path = view.get("path")
            if isinstance(view_path, str) and view_path:
                if isinstance(key, str) and key:
                    base_paths.append(f"{view_path}/{key}")
    seen: set[str] = set()
    ordered: list[str] = []
    for path in base_paths:
        if path in seen:
            continue
        if "small--api" in path:
            continue
        seen.add(path)
        ordered.append(path)
    return ordered


def _try_get_json_with_bases(
    path: str,
    base_paths: list[str],
    params: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    last_exc: Exception | None = None
    for base in base_paths:
        try:
            data = _get_json_full(f"{HOST_URL}{base}{path}", params=params)
            return data, base
        except Exception as exc:
            last_exc = exc
            continue
    raise last_exc or RuntimeError(f"request failed for {path}")


def main() -> int:
    try:
        api_list = _load_api_list()
        base_paths = _collect_base_paths(api_list)

        health, health_base = _try_get_json_with_bases("/health", base_paths)
        print("health:", health)

        meta, meta_base = _try_get_json_with_bases("/meta", base_paths)
        print("meta:", meta.get("image"))

        defect_classes, classes_base = _try_get_json_with_bases("/defect-classes", base_paths)
        print("defect classes:", defect_classes.get("num"))

        steels, steels_base = _try_get_json_with_bases("/steels", base_paths, params={"limit": 1})
        items = steels.get("steels") or []
        if not items:
            print("no steels returned; aborting further checks")
            return 0

        seq_no = items[0].get("seq_no")
        if seq_no is None:
            print("missing seq_no in steels response")
            return 1

        defects, defects_base = _try_get_json_with_bases(f"/defects/{seq_no}", base_paths)
        print("defects count:", len(defects.get("defects") or []))

        steel_meta, steel_meta_base = _try_get_json_with_bases(f"/steel-meta/{seq_no}", base_paths)
        surface_images = steel_meta.get("surface_images") or []
        print("surface_images:", surface_images)

        if surface_images:
            image_base = steel_meta_base
            surface = surface_images[0].get("surface", "top")
            frame_count = surface_images[0].get("frame_count") or 0
            image_index = 0 if frame_count <= 0 else min(1, frame_count - 1)
            frame_url = f"{HOST_URL}{image_base}/images/frame"
            frame_bytes, frame_type = _get_bytes_full(
                frame_url,
                params={
                    "surface": surface,
                    "seq_no": seq_no,
                    "image_index": image_index,
                },
            )
            print("frame image:", len(frame_bytes), frame_type)

            tile_url = f"{HOST_URL}{image_base}/images/tile"
            tile_bytes, tile_type = _get_bytes_full(
                tile_url,
                params={
                    "surface": surface,
                    "seq_no": seq_no,
                    "level": 0,
                    "tile_x": 0,
                    "tile_y": 0,
                    "tile_size": surface_images[0].get("image_height") or 512,
                },
            )
            print("tile image:", len(tile_bytes), tile_type)

        ws_ok = True
        ws_base = f"{HOST_URL}{base_paths[0]}"
        ws_ok = _ws_read_once(ws_base, f"{base_paths[0]}/cache/ws") and ws_ok
        ws_ok = _ws_read_once(ws_base, f"{base_paths[0]}/ws/system-metrics") and ws_ok

        for path in base_paths:
            _check_api_base(f"{HOST_URL}{path}", f"base={path}")

        if not ws_ok:
            return 1
        return 0
    except requests.RequestException as exc:
        print("request failed:", exc)
        return 1
    except ValueError as exc:
        print("invalid json:", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
