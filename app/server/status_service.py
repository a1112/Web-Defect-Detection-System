from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from typing import Any

from functools import lru_cache


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_state(value: str | None) -> str:
    if not value:
        return "ready"
    lowered = str(value).strip().lower()
    if lowered in {"ok", "ready", "idle"}:
        return "ready"
    if lowered in {"run", "running", "busy"}:
        return "running"
    if lowered in {"warn", "warning"}:
        return "warning"
    if lowered in {"error", "failed", "fatal"}:
        return "error"
    return lowered


def _state_weight(state: str) -> int:
    state = _normalize_state(state)
    if state == "error":
        return 3
    if state == "warning":
        return 2
    if state == "running":
        return 1
    return 0


class StatusService:
    def __init__(self, *, max_logs: int = 500) -> None:
        self._lock = threading.Lock()
        self._services: dict[str, dict[str, Any]] = {}
        self._logs: dict[str, deque[dict[str, Any]]] = {}
        self._log_counters: dict[str, int] = {}
        self._max_logs = max_logs

    def register_service(self, name: str, *, label: str | None = None, priority: int = 0) -> None:
        if not name:
            return
        with self._lock:
            entry = self._services.get(name)
            if entry is None:
                entry = {
                    "name": name,
                    "label": label or name,
                    "priority": int(priority or 0),
                    "state": "ready",
                    "message": "系统就绪",
                    "data": {},
                    "updated_at": _now_str(),
                    "version": 0,
                }
                self._services[name] = entry
            else:
                if label:
                    entry["label"] = label
                if priority is not None:
                    entry["priority"] = int(priority or 0)

    def update_service(
        self,
        name: str,
        *,
        state: str | None = None,
        message: str | None = None,
        data: dict[str, Any] | None = None,
        label: str | None = None,
        priority: int | None = None,
    ) -> None:
        if not name:
            return
        with self._lock:
            entry = self._services.get(name)
            if entry is None:
                entry = {
                    "name": name,
                    "label": label or name,
                    "priority": int(priority or 0),
                    "state": "ready",
                    "message": "系统就绪",
                    "data": {},
                    "updated_at": _now_str(),
                    "version": 0,
                }
                self._services[name] = entry
            if label:
                entry["label"] = label
            if priority is not None:
                entry["priority"] = int(priority or 0)
            if state is not None:
                entry["state"] = _normalize_state(state)
            if message is not None:
                entry["message"] = str(message)
            if data is not None:
                entry["data"] = data
            entry["updated_at"] = _now_str()
            entry["version"] = int(entry.get("version") or 0) + 1

    def append_log(self, name: str, *, level: str, message: str, data: dict[str, Any] | None = None) -> None:
        if not name:
            return
        with self._lock:
            counter = self._log_counters.get(name, 0) + 1
            self._log_counters[name] = counter
            entry = {
                "id": counter,
                "time": _now_str(),
                "level": str(level or "info"),
                "message": str(message),
                "data": data or {},
            }
            buffer = self._logs.setdefault(name, deque(maxlen=self._max_logs))
            buffer.append(entry)

    def list_services(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "name": item.get("name"),
                    "label": item.get("label"),
                    "priority": item.get("priority"),
                    "state": item.get("state"),
                    "message": item.get("message"),
                    "data": item.get("data") or {},
                    "updated_at": item.get("updated_at"),
                }
                for item in self._services.values()
            ]

    def get_logs(self, name: str | None, *, cursor: int = 0, limit: int = 200) -> dict[str, Any]:
        with self._lock:
            if name and name != "all":
                buffer = self._logs.get(name, deque())
                items = [item for item in buffer if int(item.get("id") or 0) > cursor]
                if cursor <= 0:
                    items = list(buffer)[-max(1, min(limit, self._max_logs)) :]
                if limit > 0:
                    items = items[-limit:]
                next_cursor = items[-1]["id"] if items else cursor
                return {"items": items, "cursor": next_cursor}

            combined: list[dict[str, Any]] = []
            for service, buffer in self._logs.items():
                items = [item for item in buffer if int(item.get("id") or 0) > cursor]
                if cursor <= 0:
                    items = list(buffer)[-max(1, min(limit, self._max_logs)) :]
                for item in items:
                    combined.append({"service": service, **item})
            combined.sort(key=lambda item: (item.get("time") or "", item.get("id") or 0))
            if limit > 0:
                combined = combined[-limit:]
            next_cursor = combined[-1]["id"] if combined else cursor
            return {"items": combined, "cursor": next_cursor}

    def clear_logs(self, name: str | None = None) -> None:
        with self._lock:
            if not name or name == "all":
                self._logs.clear()
                self._log_counters.clear()
                return
            self._logs.pop(name, None)
            self._log_counters.pop(name, None)

    def collect_report(
        self,
        last_versions: dict[str, int] | None = None,
        last_cursors: dict[str, int] | None = None,
        *,
        log_limit: int = 200,
    ) -> tuple[list[dict[str, Any]], dict[str, int], list[dict[str, Any]], dict[str, int]]:
        last_versions = last_versions or {}
        last_cursors = last_cursors or {}
        services_delta: list[dict[str, Any]] = []
        next_versions: dict[str, int] = {}
        logs_delta: list[dict[str, Any]] = []
        next_cursors: dict[str, int] = dict(last_cursors)
        with self._lock:
            for name, item in self._services.items():
                version = int(item.get("version") or 0)
                next_versions[name] = version
                if last_versions.get(name) == version:
                    continue
                services_delta.append(
                    {
                        "name": item.get("name"),
                        "label": item.get("label"),
                        "priority": item.get("priority"),
                        "state": item.get("state"),
                        "message": item.get("message"),
                        "data": item.get("data") or {},
                        "updated_at": item.get("updated_at"),
                    }
                )

            for name, buffer in self._logs.items():
                cursor = int(last_cursors.get(name) or 0)
                items = [item for item in buffer if int(item.get("id") or 0) > cursor]
                if log_limit > 0 and len(items) > log_limit:
                    items = items[-log_limit:]
                for item in items:
                    logs_delta.append({"service": name, **item})
                if buffer:
                    next_cursors[name] = buffer[-1]["id"]
        return services_delta, next_versions, logs_delta, next_cursors

    def get_simple_status(self) -> dict[str, Any]:
        with self._lock:
            services = list(self._services.values())
        if not services:
            return {"state": "ready", "message": "系统就绪"}

        def _pick(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
            if not candidates:
                return None
            def score(item: dict[str, Any]) -> tuple[int, int, str]:
                priority = int(item.get("priority") or 0)
                updated = str(item.get("updated_at") or "")
                return (priority, _state_weight(item.get("state")), updated)
            return max(candidates, key=score)

        errors = [item for item in services if _normalize_state(item.get("state")) == "error"]
        selected = _pick(errors)
        if not selected:
            running = [item for item in services if _normalize_state(item.get("state")) == "running"]
            selected = _pick(running)

        if not selected:
            image_service = next((item for item in services if item.get("name") == "image_generate"), None)
            if image_service and image_service.get("message") and image_service.get("message") != "系统就绪":
                selected = image_service

        if not selected:
            return {"state": "ready", "message": "系统就绪"}

        return {
            "state": selected.get("state"),
            "message": selected.get("message") or "系统就绪",
            "service": selected.get("name"),
            "label": selected.get("label"),
            "priority": selected.get("priority"),
            "data": selected.get("data") or {},
            "updated_at": selected.get("updated_at"),
        }


@lru_cache()
def get_status_service() -> StatusService:
    service = StatusService()
    service.register_service("image_generate", label="图像生成", priority=90)
    service.register_service("cache_generate", label="缓存生成", priority=80)
    service.register_service("data_refresh", label="数据刷新", priority=70)
    service.register_service("data_warmup", label="数据预热", priority=60)
    service.register_service("database", label="数据库连接", priority=100)
    service.register_service("image_path", label="图像路径", priority=95)
    return service
