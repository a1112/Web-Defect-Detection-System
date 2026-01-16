from __future__ import annotations

from pydantic import BaseModel, Field


class OptimizedMemoryCacheSettings(BaseModel):
    """优化的内存缓存配置"""
    
    # 基础配置
    max_frames: int = Field(default=128, ge=-1, description="帧缓存数量")
    max_tiles: int = Field(default=512, ge=-1, description="瓦片缓存数量")
    max_mosaics: int = Field(default=16, ge=-1, description="马赛克缓存数量")
    max_defect_crops: int = Field(default=512, ge=-1, description="缺陷裁剪缓存数量")
    ttl_seconds: int = Field(default=300, ge=1, description="TTL时间(秒)")
    
    # 高级配置
    enable_compression: bool = Field(default=True, description="启用内存压缩")
    enable_adaptive_cache: bool = Field(default=True, description="启用自适应缓存")
    concurrent_segments: int = Field(default=16, ge=1, le=64, description="并发分段数")
    max_memory_mb: int = Field(default=1024, ge=128, description="最大内存使用(MB)")
    
    # 预取优化
    prefetch_workers: int = Field(default=4, ge=1, le=8, description="预取工作线程数")
    prefetch_queue_size: int = Field(default=10000, ge=1000, description="预取队列大小")
    prefetch_batch_size: int = Field(default=20, ge=5, le=100, description="预取批次大小")
    
    # 智能预热
    enable_smart_warmup: bool = Field(default=True, description="启用智能预热")
    warmup_threshold: int = Field(default=3, ge=1, description="预热阈值")
    pattern_learning_enabled: bool = Field(default=True, description="启用模式学习")


class OptimizedDiskCacheSettings(BaseModel):
    """优化的磁盘缓存配置"""
    
    disk_cache_enabled: bool = Field(default=True, description="启用磁盘缓存")
    disk_cache_max_records: int = Field(default=50000, ge=1000, description="最大记录数")
    disk_cache_max_size_gb: int = Field(default=10, ge=1, description="最大缓存大小(GB)")
    
    # 写入优化
    async_write_enabled: bool = Field(default=True, description="启用异步写入")
    write_buffer_size: int = Field(default=100, ge=10, description="写入缓冲区大小")
    flush_interval_seconds: int = Field(default=30, ge=5, description="刷新间隔(秒)")
    
    # 缓存策略
    enable_compression: bool = Field(default=True, description="启用磁盘压缩")
    cache_layout: str = Field(default="hierarchical", description="缓存布局模式")
    cleanup_policy: str = Field(default="lru", description="清理策略")


class PerformanceMonitoringSettings(BaseModel):
    """性能监控配置"""
    
    metrics_enabled: bool = Field(default=True, description="启用指标收集")
    stats_interval_seconds: int = Field(default=60, ge=10, description="统计间隔(秒)")
    detailed_logging: bool = Field(default=False, description="详细日志")
    
    # 告警配置
    memory_usage_threshold: float = Field(default=0.8, ge=0.1, le=0.95, description="内存使用阈值")
    cache_hit_rate_threshold: float = Field(default=0.7, ge=0.1, le=0.95, description="缓存命中率阈值")


# 推荐的优化配置
PRODUCTION_CONFIG = OptimizedMemoryCacheSettings(
    max_frames=256,
    max_tiles=1024,
    max_mosaics=32,
    max_defect_crops=1024,
    ttl_seconds=600,
    enable_compression=True,
    enable_adaptive_cache=True,
    concurrent_segments=32,
    max_memory_mb=2048,
    prefetch_workers=6,
    prefetch_queue_size=20000,
    prefetch_batch_size=50,
    enable_smart_warmup=True,
    warmup_threshold=2,
    pattern_learning_enabled=True,
)

DEVELOPMENT_CONFIG = OptimizedMemoryCacheSettings(
    max_frames=64,
    max_tiles=256,
    max_mosaics=8,
    max_defect_crops=256,
    ttl_seconds=180,
    enable_compression=False,
    enable_adaptive_cache=False,
    concurrent_segments=8,
    max_memory_mb=512,
    prefetch_workers=2,
    prefetch_queue_size=5000,
    prefetch_batch_size=20,
    enable_smart_warmup=False,
    warmup_threshold=5,
    pattern_learning_enabled=False,
)

HIGH_PERFORMANCE_CONFIG = OptimizedMemoryCacheSettings(
    max_frames=512,
    max_tiles=2048,
    max_mosaics=64,
    max_defect_crops=2048,
    ttl_seconds=1200,
    enable_compression=True,
    enable_adaptive_cache=True,
    concurrent_segments=64,
    max_memory_mb=4096,
    prefetch_workers=8,
    prefetch_queue_size=50000,
    prefetch_batch_size=100,
    enable_smart_warmup=True,
    warmup_threshold=1,
    pattern_learning_enabled=True,
)