import os
import time
import pickle
import hashlib
import structlog
from functools import wraps
from typing import Any, Optional

log = structlog.get_logger("cache_manager")

CACHE_DIR = "cache_data"
from settings import CACHE_RETAIN_DAYS

class CacheManager:
    """简单文件缓存管理器（自动清理过期文件）"""
    
    def __init__(self, cache_dir: str = CACHE_DIR):
        self.cache_dir = cache_dir
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        # 启动时自动清理 7 天以上的过期缓存
        self.cleanup_expired(max_age_days=CACHE_RETAIN_DAYS)
            
    def _get_cache_path(self, key: str) -> str:
        """获取缓存文件路径"""
        filename = hashlib.md5(key.encode('utf-8')).hexdigest() + ".pkl"
        return os.path.join(self.cache_dir, filename)
        
    def get(self, key: str, max_age_days: float = 1.0) -> Optional[Any]:
        """获取缓存数据（过期自动删除文件）"""
        path = self._get_cache_path(key)
        
        if not os.path.exists(path):
            return None
            
        try:
            mtime = os.path.getmtime(path)
            if (time.time() - mtime) > (max_age_days * 86400):
                # 过期，删除文件
                try:
                    os.remove(path)
                except OSError:
                    pass
                return None
                
            with open(path, 'rb') as f:
                return pickle.load(f)
        except Exception as e:
            log.warning("cache_read_error", error=str(e))
            return None
            
    def set(self, key: str, data: Any):
        """写入缓存"""
        path = self._get_cache_path(key)
        try:
            with open(path, 'wb') as f:
                pickle.dump(data, f)
        except Exception as e:
            log.warning("cache_write_error", error=str(e))
    
    def cleanup_expired(self, max_age_days: float = 7.0):
        """清理过期缓存文件"""
        if not os.path.exists(self.cache_dir):
            return
        
        now = time.time()
        removed = 0
        for f in os.listdir(self.cache_dir):
            if not f.endswith('.pkl'):
                continue
            path = os.path.join(self.cache_dir, f)
            try:
                if (now - os.path.getmtime(path)) > (max_age_days * 86400):
                    os.remove(path)
                    removed += 1
            except OSError:
                pass
        
        if removed > 0:
            log.info("cache_cleanup_done", removed=removed, max_age_days=max_age_days)
            
    def clear(self):
        """清空全部缓存"""
        for f in os.listdir(self.cache_dir):
            path = os.path.join(self.cache_dir, f)
            try:
                os.remove(path)
            except OSError:
                pass

# 全局实例
cache_manager = CacheManager()

def cache_data(expire_days: float = 1.0):
    """
    缓存装饰器
    :param expire_days: 过期天数
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key_parts = [func.__name__]
            # 跳过实例方法的 self 参数，避免不同实例生成不同 key
            effective_args = args[1:] if args and hasattr(args[0], func.__name__) else args
            key_parts.extend([str(a) for a in effective_args])
            key_parts.extend([f"{k}={v}" for k, v in sorted(kwargs.items())])
            key = "|".join(key_parts)
            
            cached = cache_manager.get(key, max_age_days=expire_days)
            if cached is not None:
                return cached
            
            result = func(*args, **kwargs)
            
            if result is not None:
                cache_manager.set(key, result)
                
            return result
        return wrapper
    return decorator

