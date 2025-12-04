from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

CONFIG_DIR = Path(__file__).resolve().parents[3] / "configs"
DEFECT_CLASS_FILE = CONFIG_DIR / "DefectClass.json"


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
    with open(DEFECT_CLASS_FILE, "r", encoding="utf-8") as fp:
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
