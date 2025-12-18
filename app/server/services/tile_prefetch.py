from __future__ import annotations

import heapq
import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

from app.server.cache.ttl_lru_cache import TtlLruCache

logger = logging.getLogger(__name__)
prefetch_logger = logging.getLogger("uvicorn.error")


@dataclass(frozen=True)
class TileRequest:
    viewer_id: str
    surface: str
    seq_no: int
    view: str
    level: int
    tile_x: int
    tile_y: int


@dataclass(frozen=True)
class SeqWarmRequest:
    viewer_id: str
    surface: str
    seq_no: int
    view: str
    level: int
    count: int


PrefetchRequest = TileRequest | SeqWarmRequest


class TilePrefetchManager:
    """
    Background tile prefetch with priority scheduling + de-dupe.

    Priorities (smaller => earlier):
      1: cross-level neighbors of requested tile
      2: adjacent seq_no warmup (seed + tiles)
    """

    def __init__(
        self,
        *,
        service: "ImageService",
        workers: int,
        ttl_seconds: int,
        log_enabled: bool = True,
        log_detail: str = "summary",
        max_pending: int = 5000,
    ):
        if workers < 1:
            raise ValueError("workers must be >= 1")
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be >= 1")
        if max_pending < 1:
            raise ValueError("max_pending must be >= 1")

        self._service = service
        self._workers = workers
        self._max_pending = max_pending
        self._log_enabled = bool(log_enabled)
        self._log_detail = str(log_detail or "summary").strip().lower()

        self._stop = threading.Event()
        self._cond = threading.Condition()
        self._heap: list[tuple[int, float, tuple, PrefetchRequest]] = []
        self._best_priority_by_key: dict[tuple, int] = {}
        self._threads: list[threading.Thread] = []
        self._active_seq_by_viewer: dict[str, int] = {}

        # Prevent repeatedly scheduling the same "adjacent seq" warmup.
        self._seq_warm_mark = TtlLruCache[tuple, bool](max_items=2048, ttl_seconds=ttl_seconds)

    def start(self) -> None:
        if self._threads:
            return
        for idx in range(self._workers):
            thread = threading.Thread(
                target=self._worker_loop,
                name=f"tile-prefetch-{idx}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)
        if self._log_enabled:
            prefetch_logger.info("tile-prefetch threads started workers=%s", self._workers)

    def stop(self) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        if self._log_enabled:
            prefetch_logger.info("tile-prefetch stop requested")

    def notify_seq_request(self, *, viewer_id: str, seq_no: int, clear_pending: bool) -> None:
        if not viewer_id:
            return
        with self._cond:
            previous = self._active_seq_by_viewer.get(viewer_id)
            if previous == seq_no:
                return
            self._active_seq_by_viewer[viewer_id] = seq_no
            if not clear_pending:
                return
            dropped = self._clear_pending_for_viewer_outside_seq(viewer_id=viewer_id, seq_no=seq_no)
            if self._log_enabled and dropped:
                prefetch_logger.info(
                    "tile-prefetch clear pending viewer=%s prev_seq=%s seq=%s dropped=%s",
                    viewer_id,
                    previous,
                    seq_no,
                    dropped,
                )
            self._cond.notify_all()

    def enqueue_tile(self, req: TileRequest, *, priority: int) -> None:
        key = (
            "tile",
            req.viewer_id,
            req.surface,
            req.seq_no,
            req.view,
            req.level,
            req.tile_x,
            req.tile_y,
        )
        self._enqueue(key, req, priority=priority)

    def enqueue_seq_warm(self, req: SeqWarmRequest, *, priority: int) -> None:
        key = ("seqwarm", req.viewer_id, req.surface, req.seq_no, req.view, req.level, req.count)
        self._enqueue(key, req, priority=priority)

    def maybe_enqueue_adjacent_warm(
        self,
        *,
        viewer_id: str,
        surface: str,
        seq_no: int,
        view: str,
        warm_levels: list[tuple[int, int]],
        priority: int,
    ) -> None:
        if not viewer_id:
            return
        mark_key = ("adjacent", viewer_id, surface, seq_no, view)
        if self._seq_warm_mark.get(mark_key):
            return
        self._seq_warm_mark.put(mark_key, True)

        for neighbor in (seq_no - 1, seq_no + 1):
            if neighbor < 0:
                continue
            for level, count in warm_levels:
                if count <= 0:
                    continue
                self.enqueue_seq_warm(
                    SeqWarmRequest(
                        viewer_id=viewer_id,
                        surface=surface,
                        seq_no=neighbor,
                        view=view,
                        level=level,
                        count=count,
                    ),
                    priority=priority,
                )

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    def _clear_pending_for_viewer_outside_seq(self, *, viewer_id: str, seq_no: int) -> None:
        drop: list[tuple] = []
        for key in self._best_priority_by_key.keys():
            # key layouts:
            # ("tile", viewer_id, surface, seq_no, ...)
            # ("seqwarm", viewer_id, surface, seq_no, ...)
            if len(key) < 4:
                continue
            if key[1] != viewer_id:
                continue
            if key[3] != seq_no:
                drop.append(key)
        for key in drop:
            self._best_priority_by_key.pop(key, None)
        return len(drop)

    def _enqueue(self, key: tuple, req: PrefetchRequest, *, priority: int) -> None:
        with self._cond:
            if len(self._best_priority_by_key) >= self._max_pending and key not in self._best_priority_by_key:
                return
            current = self._best_priority_by_key.get(key)
            if current is not None and current <= priority:
                return
            self._best_priority_by_key[key] = priority
            heapq.heappush(self._heap, (priority, time.monotonic(), key, req))
            self._cond.notify()
        if self._log_enabled and self._log_detail == "task":
            prefetch_logger.info("tile-prefetch enqueue priority=%s key=%s req=%s", priority, key, req)

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            item: tuple[int, float, tuple, PrefetchRequest] | None = None
            with self._cond:
                while not self._heap and not self._stop.is_set():
                    self._cond.wait(timeout=0.5)
                if self._stop.is_set():
                    break
                while self._heap:
                    item = heapq.heappop(self._heap)
                    priority, _, key, _ = item
                    best = self._best_priority_by_key.get(key)
                    if best is None or best != priority:
                        item = None
                        continue
                    self._best_priority_by_key.pop(key, None)
                    break
            if item is None:
                continue
            _, _, _, req = item
            try:
                self._execute(req)
            except Exception:
                logger.debug("tile-prefetch task failed req=%s", req, exc_info=True)

    def _execute(self, req: PrefetchRequest) -> None:
        if isinstance(req, TileRequest):
            if self._log_enabled and self._log_detail == "task":
                prefetch_logger.info(
                    "tile-prefetch run tile viewer=%s seq=%s level=%s x=%s y=%s",
                    req.viewer_id,
                    req.seq_no,
                    req.level,
                    req.tile_x,
                    req.tile_y,
                )
            self._service._get_tile_impl(  # noqa: SLF001
                surface=req.surface,
                seq_no=req.seq_no,
                view=req.view,
                level=req.level,
                tile_x=req.tile_x,
                tile_y=req.tile_y,
                orientation="vertical",
                fmt="JPEG",
                trigger_prefetch=False,
                viewer_id=req.viewer_id,
            )
            return

        if isinstance(req, SeqWarmRequest):
            if self._log_enabled and self._log_detail == "task":
                prefetch_logger.info(
                    "tile-prefetch run seqwarm viewer=%s seq=%s level=%s count=%s",
                    req.viewer_id,
                    req.seq_no,
                    req.level,
                    req.count,
                )
            coords = self._service._first_tile_coords(  # noqa: SLF001
                surface=req.surface,
                seq_no=req.seq_no,
                view=req.view,
                level=req.level,
                count=req.count,
            )
            for tile_x, tile_y in coords:
                self.enqueue_tile(
                    TileRequest(
                        viewer_id=req.viewer_id,
                        surface=req.surface,
                        seq_no=req.seq_no,
                        view=req.view,
                        level=req.level,
                        tile_x=tile_x,
                        tile_y=tile_y,
                    ),
                    priority=2,
                )
            if self._log_enabled and self._log_detail == "summary" and coords:
                prefetch_logger.info(
                    "tile-prefetch seqwarm scheduled viewer=%s seq=%s level=%s tiles=%s",
                    req.viewer_id,
                    req.seq_no,
                    req.level,
                    len(coords),
                )
            return

        raise TypeError(f"Unknown request type: {type(req)!r}")
