from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Generic, MutableMapping, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class LRUCache(Generic[K, V]):
    """
    Lightweight thread-safe LRU cache for binary/image artifacts.
    """

    def __init__(self, max_items: int = 128):
        if max_items < 1:
            raise ValueError("max_items must be >= 1")
        self._max_items = max_items
        self._store: MutableMapping[K, V] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: K) -> V | None:
        with self._lock:
            value = self._store.get(key)
            if value is None:
                return None
            self._store.move_to_end(key)
            return value

    def put(self, key: K, value: V) -> None:
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = value
            if len(self._store) > self._max_items:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        return len(self._store)

