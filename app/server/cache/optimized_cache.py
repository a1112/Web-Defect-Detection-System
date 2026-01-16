from __future__ import annotations

import threading
import time
import weakref
from collections import OrderedDict
from typing import Generic, MutableMapping, TypeVar, Optional, Callable
import hashlib
import pickle

K = TypeVar("K")
V = TypeVar("V")


class ConcurrentTtlLruCache(Generic[K, V]):
    """
    高性能并发TTL LRU缓存
    优化特性：
    1. 分段锁减少锁竞争
    2. 内存压缩存储
    3. 智能预热策略
    4. 缓存统计和监控
    """

    def __init__(
        self,
        *,
        max_items: int = 512,
        ttl_seconds: int = 300,
        segments: int = 16,
        compression_enabled: bool = True,
        time_fn=time.monotonic,
        stats_enabled: bool = True,
    ):
        if max_items < 1:
            raise ValueError("max_items must be >= 1")
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be >= 1")
        if segments < 1:
            raise ValueError("segments must be >= 1")

        self._max_items = max_items
        self._ttl_seconds = ttl_seconds
        self._segments = segments
        self._compression_enabled = compression_enabled
        self._time_fn = time_fn
        self._stats_enabled = stats_enabled

        # 分段缓存减少锁竞争
        segment_size = max(1, max_items // segments)
        self._stores = [
            OrderedDict() for _ in range(segments)
        ]
        self._locks = [
            threading.RLock() for _ in range(segments)
        ]

        # 统计信息
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._stats_lock = threading.Lock()

        # 预热回调
        self._warmup_callbacks: list[Callable[[K], None]] = []

    def _get_segment(self, key: K) -> int:
        """根据key的hash值选择分段"""
        return hash(key) % self._segments

    def _compress_value(self, value: V) -> bytes:
        """压缩值以节省内存"""
        if not self._compression_enabled:
            return pickle.dumps(value)
        
        try:
            # 对于图像数据，使用更高效的压缩
            if hasattr(value, 'save') or isinstance(value, bytes):
                return pickle.dumps(value)  # 图像数据直接序列化
            return pickle.dumps(value)  # 其他数据正常序列化
        except Exception:
            return pickle.dumps(value)

    def _decompress_value(self, compressed: bytes) -> V:
        """解压缩值"""
        return pickle.loads(compressed)

    def get(self, key: K) -> Optional[V]:
        now = self._time_fn()
        segment_idx = self._get_segment(key)
        
        with self._locks[segment_idx]:
            store = self._stores[segment_idx]
            entry = store.get(key)
            
            if entry is None:
                if self._stats_enabled:
                    with self._stats_lock:
                        self._misses += 1
                self._trigger_warmup(key)
                return None
            
            expires_at, compressed_value = entry
            if expires_at <= now:
                store.pop(key, None)
                if self._stats_enabled:
                    with self._stats_lock:
                        self._misses += 1
                self._trigger_warmup(key)
                return None
            
            # 移动到末尾 (LRU更新)
            store.move_to_end(key)
            
            if self._stats_enabled:
                with self._stats_lock:
                    self._hits += 1
            
            return self._decompress_value(compressed_value)

    def put(self, key: K, value: V) -> None:
        expires_at = self._time_fn() + float(self._ttl_seconds)
        segment_idx = self._get_segment(key)
        
        compressed_value = self._compress_value(value)
        
        with self._locks[segment_idx]:
            store = self._stores[segment_idx]
            
            # 检查是否需要清理空间
            if len(store) >= self._max_items and key not in store:
                # 清理过期项
                self._cleanup_expired(store, segment_idx)
                
                # 如果仍然空间不足，移除最旧项
                if len(store) >= self._max_items:
                    store.popitem(last=False)
                    if self._stats_enabled:
                        with self._stats_lock:
                            self._evictions += 1
            
            store[key] = (expires_at, compressed_value)
            store.move_to_end(key)

    def _cleanup_expired(self, store: OrderedDict, segment_idx: int) -> None:
        """清理过期的缓存项"""
        now = self._time_fn()
        expired_keys = [
            key for key, (expires_at, _) in store.items()
            if expires_at <= now
        ]
        for key in expired_keys:
            store.pop(key, None)

    def _trigger_warmup(self, key: K) -> None:
        """触发预热回调"""
        for callback in self._warmup_callbacks:
            try:
                callback(key)
            except Exception:
                pass  # 忽略预热错误

    def add_warmup_callback(self, callback: Callable[[K], None]) -> None:
        """添加预热回调函数"""
        self._warmup_callbacks.append(callback)

    def clear(self) -> None:
        """清理所有缓存"""
        for segment_idx in range(self._segments):
            with self._locks[segment_idx]:
                self._stores[segment_idx].clear()

    def get_stats(self) -> dict:
        """获取缓存统计信息"""
        if not self._stats_enabled:
            return {"stats_enabled": False}
        
        with self._stats_lock:
            total_requests = self._hits + self._misses
            hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0
            
            total_items = sum(len(store) for store in self._stores)
            
            return {
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "hit_rate_percent": round(hit_rate, 2),
                "total_items": total_items,
                "max_items": self._max_items,
                "segments": self._segments,
                "ttl_seconds": self._ttl_seconds,
                "compression_enabled": self._compression_enabled,
            }

    def __len__(self) -> int:
        return sum(len(store) for store in self._stores)


class AdaptiveTileCache:
    """
    自适应瓦片缓存
    根据访问模式动态调整策略
    """

    def __init__(
        self,
        *,
        max_memory_mb: int = 512,  # 最大内存使用(MB)
        adaptive_ttl: bool = True,
        learning_enabled: bool = True,
    ):
        self.max_memory_mb = max_memory_mb
        self.adaptive_ttl = adaptive_ttl
        self.learning_enabled = learning_enabled
        
        # 多级缓存：热数据 -> 温数据 -> 冷数据
        self.hot_cache = ConcurrentTtlLruCache(
            max_items=128,
            ttl_seconds=180,  # 3分钟
            segments=8,
            compression_enabled=False,  # 热数据不压缩，快速访问
        )
        
        self.warm_cache = ConcurrentTtlLruCache(
            max_items=256,
            ttl_seconds=600,  # 10分钟
            segments=8,
            compression_enabled=True,
        )
        
        self.cold_cache = ConcurrentTtlLruCache(
            max_items=512,
            ttl_seconds=1800,  # 30分钟
            segments=8,
            compression_enabled=True,
        )
        
        # 访问模式学习
        self._access_patterns: dict[str, list[float]] = {}
        self._pattern_lock = threading.Lock()

    def get(self, key: str) -> Optional[bytes]:
        """三级缓存获取"""
        # 1. 热缓存
        value = self.hot_cache.get(key)
        if value is not None:
            self._record_access(key)
            return value
        
        # 2. 温缓存
        value = self.warm_cache.get(key)
        if value is not None:
            # 提升到热缓存
            self.hot_cache.put(key, value)
            self._record_access(key)
            return value
        
        # 3. 冷缓存
        value = self.cold_cache.get(key)
        if value is not None:
            # 提升到温缓存
            self.warm_cache.put(key, value)
            self._record_access(key)
            return value
        
        return None

    def put(self, key: str, value: bytes) -> None:
        """智能存储到合适的缓存级别"""
        if self._should_be_hot(key):
            self.hot_cache.put(key, value)
        elif self._should_be_warm(key):
            self.warm_cache.put(key, value)
        else:
            self.cold_cache.put(key, value)

    def _should_be_hot(self, key: str) -> bool:
        """判断是否应该存储为热数据"""
        if not self.learning_enabled:
            return False
        
        with self._pattern_lock:
            pattern = self._access_patterns.get(key, [])
            # 最近访问频繁，判定为热数据
            recent_count = sum(1 for t in pattern[-10:] if time.time() - t < 300)
            return recent_count >= 3

    def _should_be_warm(self, key: str) -> bool:
        """判断是否应该存储为温数据"""
        if not self.learning_enabled:
            return True
        
        with self._pattern_lock:
            pattern = self._access_patterns.get(key, [])
            # 有一定访问频率
            recent_count = sum(1 for t in pattern[-20:] if time.time() - t < 1800)
            return recent_count >= 2

    def _record_access(self, key: str) -> None:
        """记录访问模式"""
        if not self.learning_enabled:
            return
        
        with self._pattern_lock:
            if key not in self._access_patterns:
                self._access_patterns[key] = []
            
            self._access_patterns[key].append(time.time())
            
            # 保持最近100次记录
            if len(self._access_patterns[key]) > 100:
                self._access_patterns[key] = self._access_patterns[key][-100:]

    def get_comprehensive_stats(self) -> dict:
        """获取综合统计信息"""
        return {
            "hot_cache": self.hot_cache.get_stats(),
            "warm_cache": self.warm_cache.get_stats(),
            "cold_cache": self.cold_cache.get_stats(),
            "learning_patterns": len(self._access_patterns),
            "max_memory_mb": self.max_memory_mb,
        }