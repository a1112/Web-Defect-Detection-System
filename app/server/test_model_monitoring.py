# 监控和性能日志模块
import logging
import time
import psutil
import threading
from typing import Dict, Any, Optional, Callable
from collections import deque, defaultdict
from datetime import datetime
from functools import wraps

logger = logging.getLogger("test_model")

# 尝试导入psutil，如果不可用则提供降级方案
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil not available, some monitoring features will be limited")


class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.metrics = defaultdict(deque)
        self.current_operation = None
        self.operation_start_time = None
        self.lock = threading.Lock()
        
        # 性能指标
        self.metrics["operation_duration"] = deque(maxlen=max_history)
        self.metrics["memory_usage"] = deque(maxlen=max_history)
        self.metrics["cpu_usage"] = deque(maxlen=max_history)
        self.metrics["error_count"] = defaultdict(int)
        self.metrics["success_count"] = defaultdict(int)
        
        # 系统资源基准
        self.baseline_resources = self._get_system_baseline()
    
    def _get_system_baseline(self) -> Dict[str, float]:
        """获取系统资源基准"""
        if not PSUTIL_AVAILABLE:
            return {"memory_mb": 0, "cpu_percent": 0, "threads": 0}
        
        process = psutil.Process()
        return {
            "memory_mb": process.memory_info().rss / 1024 / 1024,
            "cpu_percent": process.cpu_percent(),
            "threads": process.num_threads(),
        }
    
    def start_operation(self, operation_name: str):
        """开始记录操作"""
        with self.lock:
            self.current_operation = operation_name
            self.operation_start_time = time.time()
            self._record_system_metrics()
    
    def end_operation(self, operation_name: str, success: bool = True, error: Optional[Exception] = None):
        """结束记录操作"""
        with self.lock:
            if self.current_operation != operation_name:
                logger.warning(f"Operation name mismatch: {self.current_operation} vs {operation_name}")
            
            duration = time.time() - self.operation_start_time if self.operation_start_time else 0
            
            self.metrics["operation_duration"].append({
                "operation": operation_name,
                "duration": duration,
                "success": success,
                "timestamp": time.time(),
            })
            
            if success:
                self.metrics["success_count"][operation_name] += 1
            else:
                self.metrics["error_count"][operation_name] += 1
            
            self._record_system_metrics()
            self.current_operation = None
            self.operation_start_time = None
            
            logger.info(
                f"Operation completed: {operation_name}",
                extra={
                    "operation": operation_name,
                    "duration_ms": duration * 1000,
                    "success": success,
                    "error": str(error) if error else None,
                }
            )
    
    def _record_system_metrics(self):
        """记录系统指标"""
        if not PSUTIL_AVAILABLE:
            return
        
        try:
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            cpu_percent = process.cpu_percent()
            
            self.metrics["memory_usage"].append({
                "value": memory_mb,
                "timestamp": time.time(),
                "delta": memory_mb - self.baseline_resources["memory_mb"],
            })
            
            self.metrics["cpu_usage"].append({
                "value": cpu_percent,
                "timestamp": time.time(),
                "delta": cpu_percent - self.baseline_resources["cpu_percent"],
            })
            
            # 检查资源使用异常
            if memory_mb > self.baseline_resources["memory_mb"] * 1.5:
                logger.warning(
                    f"High memory usage detected: {memory_mb:.2f}MB (baseline: {self.baseline_resources['memory_mb']:.2f}MB)",
                    extra={"memory_mb": memory_mb, "baseline_mb": self.baseline_resources["memory_mb"]}
                )
            
            if cpu_percent > 80:
                logger.warning(
                    f"High CPU usage detected: {cpu_percent:.1f}% (baseline: {self.baseline_resources['cpu_percent']:.1f}%)",
                    extra={"cpu_percent": cpu_percent, "baseline_cpu": self.baseline_resources["cpu_percent"]}
                )
                
        except Exception as e:
            logger.warning(f"Failed to record system metrics: {str(e)}")
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """获取性能摘要"""
        with self.lock:
            summary = {
                "current_operation": self.current_operation,
                "operation_duration_seconds": time.time() - self.operation_start_time if self.operation_start_time else 0,
                "operation_count": defaultdict(int),
                "average_duration_by_operation": defaultdict(float),
                "success_rate_by_operation": defaultdict(float),
                "current_memory_mb": 0,
                "current_cpu_percent": 0,
                "baseline_memory_mb": self.baseline_resources.get("memory_mb", 0),
                "baseline_cpu_percent": self.baseline_resources.get("cpu_percent", 0),
            }
            
            # 统计每个操作的性能
            durations_by_op = defaultdict(list)
            for record in self.metrics["operation_duration"]:
                op = record["operation"]
                durations_by_op[op].append(record["duration"])
                summary["operation_count"][op] += 1
            
            for op, durations in durations_by_op.items():
                summary["average_duration_by_operation"][op] = sum(durations) / len(durations)
                
                success_count = self.metrics["success_count"].get(op, 0)
                error_count = self.metrics["error_count"].get(op, 0)
                total = success_count + error_count
                if total > 0:
                    summary["success_rate_by_operation"][op] = success_count / total
            
            # 当前资源使用
            if self.metrics["memory_usage"]:
                latest_memory = self.metrics["memory_usage"][-1]
                summary["current_memory_mb"] = latest_memory["value"]
            
            if self.metrics["cpu_usage"]:
                latest_cpu = self.metrics["cpu_usage"][-1]
                summary["current_cpu_percent"] = latest_cpu["value"]
            
            return dict(summary)
    
    def get_detailed_metrics(self, operation: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        """获取详细的性能指标"""
        with self.lock:
            metrics = {}
            
            if operation:
                # 特定操作的指标
                metrics["operation"] = operation
                operation_records = [
                    r for r in self.metrics["operation_duration"]
                    if r["operation"] == operation
                ]
                
                if operation_records:
                    latest = operation_records[-1]
                    metrics["latest_execution"] = {
                        "duration_ms": latest["duration"] * 1000,
                        "success": latest["success"],
                        "timestamp": datetime.fromtimestamp(latest["timestamp"]).isoformat(),
                    }
                    
                    durations = [r["duration"] for r in operation_records[-limit:]]
                    metrics["recent_executions"] = {
                        "count": len(durations),
                        "average_duration_ms": sum(durations) / len(durations) * 1000,
                        "min_duration_ms": min(durations) * 1000,
                        "max_duration_ms": max(durations) * 1000,
                        "success_rate": sum(1 for r in operation_records[-limit:] if r["success"]) / len(operation_records[-limit:]),
                    }
            else:
                # 所有操作的指标
                metrics["all_operations"] = {
                    "total_executions": len(self.metrics["operation_duration"]),
                    "recent_durations_ms": [
                        r["duration"] * 1000 for r in list(self.metrics["operation_duration"])[-limit:]
                    ],
                }
            
            # 系统资源指标
            if self.metrics["memory_usage"]:
                recent_memory = list(self.metrics["memory_usage"])[-limit:]
                metrics["memory_usage"] = {
                    "current_mb": recent_memory[-1]["value"],
                    "average_mb": sum(r["value"] for r in recent_memory) / len(recent_memory),
                    "max_mb": max(r["value"] for r in recent_memory),
                    "min_mb": min(r["value"] for r in recent_memory),
                    "baseline_mb": self.baseline_resources.get("memory_mb", 0),
                    "delta_mb": recent_memory[-1]["value"] - self.baseline_resources.get("memory_mb", 0),
                }
            
            if self.metrics["cpu_usage"]:
                recent_cpu = list(self.metrics["cpu_usage"])[-limit:]
                metrics["cpu_usage"] = {
                    "current_percent": recent_cpu[-1]["value"],
                    "average_percent": sum(r["value"] for r in recent_cpu) / len(recent_cpu),
                    "max_percent": max(r["value"] for r in recent_cpu),
                    "min_percent": min(r["value"] for r in recent_cpu),
                    "baseline_percent": self.baseline_resources.get("cpu_percent", 0),
                    "delta_percent": recent_cpu[-1]["value"] - self.baseline_resources.get("cpu_percent", 0),
                }
            
            # 错误统计
            metrics["error_summary"] = {
                "total_errors": sum(self.metrics["error_count"].values()),
                "operations_with_errors": len(self.metrics["error_count"]),
                "errors_by_operation": dict(self.metrics["error_count"]),
            }
            
            return metrics


def monitor_performance(operation_name: str = None):
    """性能监控装饰器"""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 获取操作名称
            op_name = operation_name or func.__name__
            
            # 获取性能监控器实例
            from app.server.test_model import get_performance_monitor
            monitor = get_performance_monitor()
            
            # 记录操作开始
            monitor.start_operation(op_name)
            
            try:
                result = func(*args, **kwargs)
                monitor.end_operation(op_name, success=True)
                return result
            except Exception as e:
                monitor.end_operation(op_name, success=False, error=e)
                raise
        
        return wrapper
    return decorator


class DetailedLogger:
    """详细日志记录器"""
    
    def __init__(self, log_file_path: Optional[str] = None):
        self.log_file_path = log_file_path
        self.logger = logging.getLogger("detailed_test_model")
        self.logger.setLevel(logging.DEBUG)
        
        if log_file_path:
            # 文件处理器
            file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
            file_handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
        
        # 控制台处理器（仅警告和错误）
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
        self.logger.addHandler(console_handler)
    
    def log_operation(self, operation: str, details: Dict[str, Any], level: str = "INFO"):
        """记录操作日志"""
        log_method = getattr(self.logger, level.lower(), self.logger.info)
        log_method(
            f"{operation}",
            extra={"operation": operation, "details": details}
        )
    
    def log_system_event(self, event_type: str, details: Dict[str, Any]):
        """记录系统事件"""
        self.logger.info(
            f"System event: {event_type}",
            extra={"event_type": event_type, "details": details}
        )
    
    def log_performance(self, operation: str, duration: float, success: bool, **kwargs):
        """记录性能日志"""
        self.logger.info(
            f"Performance: {operation} - {duration:.3f}s - {'success' if success else 'failed'}",
            extra={
                "performance": True,
                "operation": operation,
                "duration_seconds": duration,
                "success": success,
                **kwargs
            }
        )
    
    def log_data_validation(self, validation_type: str, result: Dict[str, Any]):
        """记录数据验证日志"""
        status = "PASS" if result.get("valid", False) else "FAIL"
        self.logger.info(
            f"Validation: {validation_type} - {status}",
            extra={
                "validation": True,
                "validation_type": validation_type,
                "status": status,
                "issues": result.get("issues", []),
                **result
            }
        )
    
    def log_error_recovery(self, error_type: str, success: bool, details: Dict[str, Any]):
        """记录错误恢复日志"""
        status = "RECOVERY_SUCCESS" if success else "RECOVERY_FAILED"
        self.logger.warning(
            f"Error recovery: {error_type} - {status}",
            extra={
                "error_recovery": True,
                "error_type": error_type,
                "status": status,
                **details
            }
        )


# 全局性能监控器实例
_global_performance_monitor: Optional[PerformanceMonitor] = None
_global_detailed_logger: Optional[DetailedLogger] = None


def get_performance_monitor() -> PerformanceMonitor:
    """获取全局性能监控器"""
    global _global_performance_monitor
    if _global_performance_monitor is None:
        _global_performance_monitor = PerformanceMonitor()
    return _global_performance_monitor


def get_detailed_logger() -> DetailedLogger:
    """获取全局详细日志记录器"""
    global _global_detailed_logger
    if _global_detailed_logger is None:
        from app.server.test_model import LOG_PATH
        _global_detailed_logger = DetailedLogger(str(LOG_PATH))
    return _global_detailed_logger


def log_with_metrics(operation_name: str):
    """带指标记录的装饰器"""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            logger.info(f"Starting: {operation_name}")
            
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                logger.info(
                    f"Completed: {operation_name} in {duration:.3f}s",
                    extra={"operation": operation_name, "duration": duration, "success": True}
                )
                
                # 同时记录到详细日志
                detailed_logger = get_detailed_logger()
                detailed_logger.log_performance(operation_name, duration, True)
                
                return result
                
            except Exception as e:
                duration = time.time() - start_time
                logger.error(
                    f"Failed: {operation_name} after {duration:.3f}s: {str(e)}",
                    extra={"operation": operation_name, "duration": duration, "success": False, "error": str(e)}
                )
                
                # 同时记录到详细日志
                detailed_logger = get_detailed_logger()
                detailed_logger.log_performance(operation_name, duration, False, error=str(e))
                
                raise
        
        return wrapper
    return decorator