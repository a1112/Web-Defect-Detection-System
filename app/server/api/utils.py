from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
import os
from typing import Optional

CONFIG_DIR = Path(__file__).resolve().parents[3] / "configs"
TEMPLATE_DIR = CONFIG_DIR / "template"
CURRENT_DIR = CONFIG_DIR / "current"
DEFAULT_DEFECT_CLASS = CURRENT_DIR / "DefectClass.json"


def _resolve_defect_class_file() -> Path:
    CURRENT_DIR.mkdir(parents=True, exist_ok=True)
    if not DEFAULT_DEFECT_CLASS.exists():
        template_defect = TEMPLATE_DIR / "DefectClass.json"
        if template_defect.exists():
            DEFAULT_DEFECT_CLASS.write_text(
                template_defect.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
    env_path = os.getenv("DEFECT_CLASS_PATH")
    if env_path:
        candidate = Path(env_path)
        if candidate.exists():
            return candidate
    line_key = os.getenv("DEFECT_LINE_KEY") or os.getenv("DEFECT_LINE_NAME")
    if line_key:
        line_path = CURRENT_DIR / "generated" / line_key / "DefectClass.json"
        if line_path.exists():
            return line_path
    return DEFAULT_DEFECT_CLASS


def grade_to_level(grade: Optional[int] | None) -> str:
    """将内部整数等级映射为 A-D 等级，用于 Web UI."""
    if grade is None:
        return "D"
    mapping = {1: "A", 2: "B", 3: "C", 4: "D"}
    return mapping.get(int(grade), "D")


def grade_to_severity(grade: Optional[int] | None) -> str:
    """根据缺陷等级粗略映射严重程度，供 Web UI 使用。"""
    if grade is None:
        return "medium"
    grade_val = int(grade)
    if grade_val <= 1:
        return "low"
    if grade_val == 2:
        return "medium"
    return "high"


@lru_cache()
def _defect_class_payload() -> dict:
    defect_class_file = _resolve_defect_class_file()
    with open(defect_class_file, "r", encoding="utf-8") as fp:
        return json.load(fp)


@lru_cache()
def _defect_class_map() -> dict[int, str]:
    payload = _defect_class_payload()
    items = payload.get("items", []) if isinstance(payload, dict) else []
    mapping: dict[int, str] = {}
    for item in items:
        try:
            class_id = int(item.get("class"))
        except Exception:
            continue
        desc = item.get("desc") or item.get("name") or "未知缺陷"
        mapping[class_id] = desc
    return mapping


def defect_class_label(class_id: Optional[int]) -> str:
    if class_id is None:
        return "未知缺陷"
    return _defect_class_map().get(int(class_id), "未知缺陷")


def get_defect_class_payload() -> dict:
    """返回缺陷字典的完整 JSON 载荷。"""
    return _defect_class_payload()
