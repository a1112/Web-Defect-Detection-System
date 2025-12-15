from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Generic, MutableMapping, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class TtlLruCache(Generic[K, V]):
    """
    Lightweight thread-safe LRU cache with TTL eviction.
    """

    def __init__(
        self,
        *,
        max_items: int = 128,
        ttl_seconds: int = 120,
        time_fn=time.monotonic,
    ):
        if max_items < 1:
            raise ValueError("max_items must be >= 1")
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be >= 1")
        self._max_items = max_items
        self._ttl_seconds = ttl_seconds
        self._time_fn = time_fn
        self._store: MutableMapping[K, tuple[float, V]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: K) -> V | None:
        now = self._time_fn()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= now:
                self._store.pop(key, None)
                return None
            self._store.move_to_end(key)
            return value

    def put(self, key: K, value: V) -> None:
        expires_at = self._time_fn() + float(self._ttl_seconds)
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (expires_at, value)
            if len(self._store) > self._max_items:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

