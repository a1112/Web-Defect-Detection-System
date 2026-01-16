# 错误处理和恢复模块
import logging
import time
import traceback
from typing import Dict, Any, Optional, Callable
from contextlib import contextmanager
from functools import wraps

logger = logging.getLogger("test_model")


class ErrorRecovery:
    """错误恢复管理器"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.error_stats = {
            "total_errors": 0,
            "recovery_success": 0,
            "recovery_failed": 0,
            "last_error_time": None,
            "errors_by_type": {}
        }
    
    def record_error(self, error: Exception, context: str = "", recovery_action: str = ""):
        """记录错误信息"""
        error_type = type(error).__name__
        self.error_stats["total_errors"] += 1
        self.error_stats["last_error_time"] = time.time()
        
        if error_type not in self.error_stats["errors_by_type"]:
            self.error_stats["errors_by_type"][error_type] = {
                "count": 0,
                "last_occurrence": None,
                "examples": []
            }
        
        self.error_stats["errors_by_type"][error_type]["count"] += 1
        self.error_stats["errors_by_type"][error_type]["last_occurrence"] = time.time()
        
        # 保存最近5个错误示例
        examples = self.error_stats["errors_by_type"][error_type]["examples"]
        if len(examples) >= 5:
            examples.pop(0)
        examples.append({
            "time": time.time(),
            "message": str(error),
            "context": context,
            "traceback": traceback.format_exc()[:500]  # 限制长度
        })
        
        logger.error(
            f"Error recorded: {error_type} - {context}",
            extra={
                "error": str(error),
                "recovery_action": recovery_action,
                "context": context
            }
        )
    
    def record_recovery(self, success: bool, context: str = ""):
        """记录恢复结果"""
        if success:
            self.error_stats["recovery_success"] += 1
        else:
            self.error_stats["recovery_failed"] += 1
        
        logger.info(
            f"Recovery {'success' if success else 'failed'}: {context}",
            extra={"context": context, "success": success}
        )
    
    def get_error_summary(self) -> Dict[str, Any]:
        """获取错误摘要"""
        summary = dict(self.error_stats)
        
        # 计算恢复成功率
        total_recovery = summary["recovery_success"] + summary["recovery_failed"]
        if total_recovery > 0:
            summary["recovery_rate"] = round(
                summary["recovery_success"] / total_recovery * 100, 2
            )
        else:
            summary["recovery_rate"] = 100.0
        
        # 添加时间信息
        if summary["last_error_time"]:
            summary["seconds_since_last_error"] = time.time() - summary["last_error_time"]
        
        return summary
    
    def get_top_errors(self, limit: int = 5) -> list:
        """获取最常发生的错误"""
        errors = []
        for error_type, data in self.error_stats["errors_by_type"].items():
            errors.append({
                "type": error_type,
                "count": data["count"],
                "last_occurrence": data["last_occurrence"]
            })
        
        errors.sort(key=lambda x: x["count"], reverse=True)
        return errors[:limit]


class RecoveryStrategy:
    """恢复策略"""
    
    @staticmethod
    def retry_with_backoff(max_retries: int = 3, backoff_factor: float = 2.0):
        """带指数退避的重试装饰器"""
        def decorator(func: Callable):
            @wraps(func)
            def wrapper(*args, **kwargs):
                last_exception = None
                
                for attempt in range(max_retries):
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        last_exception = e
                        
                        if attempt < max_retries - 1:
                            wait_time = backoff_factor ** attempt
                            logger.warning(
                                f"Retry attempt {attempt + 1}/{max_retries} after {wait_time}s error: {str(e)}"
                            )
                            time.sleep(wait_time)
                        else:
                            logger.error(f"All {max_retries} attempts failed: {str(e)}")
                
                # 所有重试都失败了，抛出最后一个异常
                raise last_exception
            
            return wrapper
        return decorator
    
    @staticmethod
    def fallback_to_default(default_value: Any):
        """回退到默认值的装饰器"""
        def decorator(func: Callable):
            @wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    logger.warning(f"Using fallback default value due to error: {str(e)}")
                    return default_value
            
            return wrapper
        return decorator
    
    @staticmethod
    def safe_execute(operation_name: str, recovery_manager: ErrorRecovery):
        """安全执行操作"""
        def decorator(func: Callable):
            @wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    recovery_manager.record_error(e, f"safe_execute:{operation_name}")
                    # 尝试恢复
                    recovery_action = f"Recovery for {operation_name}"
                    try:
                        # 这里可以添加特定的恢复逻辑
                        recovery_manager.record_recovery(True, recovery_action)
                        return None  # 返回None表示恢复成功但无结果
                    except Exception as recovery_e:
                        recovery_manager.record_recovery(False, recovery_action)
                        recovery_manager.record_error(recovery_e, f"recovery_failed:{operation_name}")
                        # 重新抛出原始异常
                        raise e
            
            return wrapper
        return decorator


@contextmanager
def safe_database_session(session_factory, recovery_manager: ErrorRecovery):
    """安全的数据库会话上下文管理器"""
    session = None
    try:
        session = session_factory()
        yield session
        session.commit()
    except Exception as e:
        recovery_manager.record_error(e, "database_session", "rollback")
        try:
            if session:
                session.rollback()
            recovery_manager.record_recovery(True, "database_rollback")
        except Exception as rollback_e:
            recovery_manager.record_recovery(False, "database_rollback")
            recovery_manager.record_error(rollback_e, "rollback_failed")
        raise
    finally:
        try:
            if session:
                session.close()
        except Exception as e:
            recovery_manager.record_error(e, "session_close_failed")


@contextmanager
def safe_file_operation(recovery_manager: ErrorRecovery, operation: str = "file"):
    """安全的文件操作上下文管理器"""
    try:
        yield
    except (FileNotFoundError, PermissionError, IOError) as e:
        recovery_manager.record_error(e, f"file_operation:{operation}", "skip")
        recovery_manager.record_recovery(True, "file_operation_skip")
    except Exception as e:
        recovery_manager.record_error(e, f"file_operation:{operation}")
        recovery_manager.record_recovery(False, "file_operation_recovery")
        raise


class HealthCheck:
    """健康检查管理器"""
    
    def __init__(self):
        self.checks = {}
        self.last_check_time = None
    
    def add_check(self, name: str, check_func: Callable, critical: bool = False):
        """添加健康检查"""
        self.checks[name] = {
            "function": check_func,
            "critical": critical,
            "last_result": None,
            "last_check_time": None
        }
    
    def run_check(self, name: str) -> Dict[str, Any]:
        """运行单个检查"""
        if name not in self.checks:
            return {
                "name": name,
                "status": "unknown",
                "error": f"Check '{name}' not found"
            }
        
        check = self.checks[name]
        try:
            result = check["function"]()
            check["last_result"] = result
            check["last_check_time"] = time.time()
            
            return {
                "name": name,
                "status": "pass" if result.get("success", False) else "fail",
                "critical": check["critical"],
                "result": result,
                "timestamp": check["last_check_time"]
            }
        except Exception as e:
            check["last_result"] = {"success": False, "error": str(e)}
            check["last_check_time"] = time.time()
            
            return {
                "name": name,
                "status": "fail",
                "critical": check["critical"],
                "error": str(e),
                "timestamp": time.time()
            }
    
    def run_all_checks(self) -> Dict[str, Any]:
        """运行所有检查"""
        self.last_check_time = time.time()
        results = []
        critical_failures = 0
        
        for name in self.checks:
            result = self.run_check(name)
            results.append(result)
            
            if result["status"] == "fail" and result["critical"]:
                critical_failures += 1
        
        return {
            "overall_status": "fail" if critical_failures > 0 else "pass",
            "critical_failures": critical_failures,
            "total_checks": len(results),
            "failed_checks": sum(1 for r in results if r["status"] == "fail"),
            "results": results,
            "timestamp": self.last_check_time
        }
    
    def get_health_status(self) -> str:
        """获取整体健康状态"""
        if not self.last_check_time:
            return "unknown"
        
        overall = self.run_all_checks()
        return overall["overall_status"]


class CircuitBreaker:
    """断路器模式实现"""
    
    def __init__(self, failure_threshold: int = 5, timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open
    
    def call(self, func: Callable, *args, **kwargs):
        """执行函数，如果断路器打开则快速失败"""
        if self.state == "open":
            if time.time() - self.last_failure_time > self.timeout:
                # 尝试恢复到半开状态
                self.state = "half-open"
                logger.info("Circuit breaker entering half-open state")
            else:
                raise Exception("Circuit breaker is open")
        
        try:
            result = func(*args, **kwargs)
            
            if self.state == "half-open":
                # 半开状态下成功，重置断路器
                self.state = "closed"
                self.failure_count = 0
                logger.info("Circuit breaker reset to closed state")
            else:
                # 正常状态下成功，重置失败计数
                self.failure_count = 0
            
            return result
            
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = "open"
                logger.warning(f"Circuit breaker opened after {self.failure_count} failures")
            
            raise e
    
    def reset(self):
        """手动重置断路器"""
        self.failure_count = 0
        self.state = "closed"
        self.last_failure_time = None
        logger.info("Circuit breaker manually reset")
    
    def get_state(self) -> Dict[str, Any]:
        """获取断路器状态"""
        return {
            "state": self.state,
            "failure_count": self.failure_count,
            "last_failure_time": self.last_failure_time,
            "failure_threshold": self.failure_threshold,
            "timeout": self.timeout
        }