from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests


def _fmt_bytes(length: int) -> str:
    if length < 1024:
        return f"{length} B"
    if length < 1024 * 1024:
        return f"{length / 1024:.1f} KB"
    return f"{length / (1024 * 1024):.1f} MB"


@dataclass
class Scenario:
    base_url: str
    seq_no: int
    steel_no: str
    steel_id: int
    surface: str
    defect_id: Optional[int] = None
    image_index: Optional[int] = None


class ApiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_binary(self, path: str, params: Dict[str, Any]):
        url = f"{self.base_url}{path}"
        resp = self.session.get(url, params=params, timeout=60)
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "application/octet-stream")


def bootstrap_scenario(client: ApiClient, args) -> Scenario:
    seq_no = args.seq_no
    steel_no = args.steel_no
    steel_id = args.steel_id
    defect_id = args.defect_id
    image_index = args.image_index
    surface = args.surface

    if not (seq_no and steel_no):
        recent = client.get_json("/api/steels", {"limit": 1})
        if not recent.get("items"):
            raise RuntimeError("No steel records available via /api/steels; provide CLI overrides")
        first = recent["items"][0]
        seq_no = seq_no or first["seq_no"]
        steel_no = steel_no or first["steel_id"]
        steel_id = steel_id or first["seq_no"]

    if steel_id is None:
        steel_id = seq_no

    defects = client.get_json(f"/api/defects/{seq_no}", {"surface": surface})
    defect_items = defects.get("items", [])
    if defect_items:
        first_defect = defect_items[0]
        defect_id = defect_id or first_defect["defect_id"]
        image_index = image_index or first_defect.get("image_index") or 0
    else:
        defect_id = defect_id or None
        image_index = image_index or 0

    return Scenario(
        base_url=client.base_url,
        seq_no=seq_no,
        steel_no=steel_no,
        steel_id=steel_id,
        defect_id=defect_id,
        image_index=image_index,
        surface=surface,
    )


def run_smoke(client: ApiClient, scenario: Scenario):
    print(f"Base URL: {scenario.base_url}")
    print(f"SeqNo={scenario.seq_no}  SteelNo={scenario.steel_no}  Surface={scenario.surface}\n")

    recent = client.get_json("/api/steels", {"limit": 5})
    print("/api/steels ->", recent["count"], "records")

    by_seq = client.get_json(f"/api/steels/seq/{scenario.seq_no}")
    print("/api/steels/seq ->", by_seq["count"])

    by_no = client.get_json(f"/api/steels/steel-no/{scenario.steel_no}")
    print("/api/steels/steel-no ->", by_no["count"])

    by_id = client.get_json(f"/api/steels/id/{scenario.steel_id}")
    print("/api/steels/id ->", by_id["count"])

    defects = client.get_json(f"/api/defects/{scenario.seq_no}", {"surface": scenario.surface})
    print("/api/defects ->", len(defects["items"]), "items")

    frame_params = {
        "surface": scenario.surface,
        "seq_no": scenario.seq_no,
        "image_index": scenario.image_index or 0,
        "width": 512,
    }
    frame_bytes, frame_type = client.get_binary("/api/images/frame", frame_params)
    print("/api/images/frame ->", frame_type, _fmt_bytes(len(frame_bytes)))

    if scenario.defect_id is not None:
        defect_bytes, _ = client.get_binary(
            f"/api/images/defect/{scenario.defect_id}", {"surface": scenario.surface}
        )
        print("/api/images/defect ->", _fmt_bytes(len(defect_bytes)))
    else:
        print("/api/images/defect -> skipped (no defects detected)")

    mosaic_bytes, _ = client.get_binary(
        "/api/images/mosaic",
        {"surface": scenario.surface, "seq_no": scenario.seq_no, "limit": 10},
    )
    print("/api/images/mosaic ->", _fmt_bytes(len(mosaic_bytes)))

    tile_bytes, _ = client.get_binary(
        "/api/images/tile",
        {
            "surface": scenario.surface,
            "seq_no": scenario.seq_no,
            "tile_x": 0,
            "tile_y": 0,
        },
    )
    print("/api/images/tile ->", _fmt_bytes(len(tile_bytes)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simple API smoke tester for the defect server")
    parser.add_argument("--base-url", default=os.getenv("BKJC_API_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--seq-no", type=int)
    parser.add_argument("--steel-no")
    parser.add_argument("--steel-id", type=int)
    parser.add_argument("--defect-id", type=int)
    parser.add_argument("--image-index", type=int)
    parser.add_argument("--surface", choices=["top", "bottom"], default="top")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    client = ApiClient(args.base_url)
    scenario = bootstrap_scenario(client, args)
    run_smoke(client, scenario)


if __name__ == "__main__":
    main()
