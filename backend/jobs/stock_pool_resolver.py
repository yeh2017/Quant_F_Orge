"""
股票池解析器
===========
根据模式（pool/hs300/zz500/all/…）动态获取目标股票代码列表。
"""

import time
import structlog
from typing import List, Optional, Dict, Tuple

log = structlog.get_logger("stock_pool")

# 静态股票池 —— 仅保留 pool（自定义）作为 custom_codes 的接收容器
# 宽基指数（hs300/zz500/zz1000）通过 Tushare index_weight 动态拉取
# 全市场（all）通过查询本地 StockBasicInfo 表
_STATIC_POOLS = {
    "pool": [],  # 占位，实际使用 custom_codes 参数
}

# 宽基指数映射
_INDEX_MAP = {
    "hs300": ("399300.SZ", "沪深300"),
    "zz500": ("000905.SH", "中证500"),
    "zz1000": ("000852.SH", "中证1000"),
}

# 宽基指数成分股内存缓存：{mode: (codes, cached_at_ts)}
# TTL = 7天，避免每次 full_sync 都重复调 Tushare index_weight
_INDEX_CACHE: Dict[str, Tuple[List[str], float]] = {}
_INDEX_CACHE_TTL = 7 * 24 * 3600  # 7天（秒）


class StockPoolResolver:
    """股票池解析"""

    def __init__(self, ts_source):
        self._ts = ts_source

    def resolve(self, mode: str, custom_codes: Optional[List[str]] = None) -> List[str]:
        """
        解析目标股票池。

        Args:
            mode: pool / hs300 / zz500 / zz1000 / all / bank / tech ...
            custom_codes: 前端传入的自定义代码列表

        Returns:
            股票代码列表 (如 ['000001.SZ', '600519.SH'])
        """
        # 1. pool 模式：优先用 custom_codes，否则查本地 DB 的活跃股票（小样本）
        if mode == "pool":
            if custom_codes:
                # 前端可能传入无后缀 code（如 "000001"），统一规范化为 DB 格式
                # 用 to_db_code 而非 to_ts_code：可转债在 DB 中存纯 6 位码
                from utils.bar_query import to_db_code
                normalized = [to_db_code(c) for c in custom_codes]
                log.info("resolve_pool", mode=mode, source="custom", count=len(normalized))
                return normalized
            # custom_codes 为空时 fallback 到本地 DB 随机取 20 只活跃股票
            return self._resolve_pool_fallback()

        # 2. 宽基指数：带 TTL 的内存缓存
        if mode in _INDEX_MAP:
            return self._resolve_index_cached(mode)

        # 3. 全市场
        if mode == "all":
            return self._resolve_all()

        # 4. 兜底：未知 mode 当作 pool 处理
        log.warning("resolve_pool_fallback", mode=mode)
        return self._resolve_pool_fallback()

    def _resolve_index_cached(self, mode: str) -> List[str]:
        """带 TTL 缓存的宽基指数成分解析（进程级内存缓存，7天过期）"""
        cached = _INDEX_CACHE.get(mode)
        if cached:
            codes, cached_at = cached
            age = time.time() - cached_at
            if age < _INDEX_CACHE_TTL:
                log.info("resolve_index_cache_hit", mode=mode,
                         count=len(codes), age_hours=round(age / 3600, 1))
                return codes
            log.info("resolve_index_cache_expired", mode=mode,
                     age_hours=round(age / 3600, 1))

        codes = self._resolve_index(mode)
        if codes and codes != _STATIC_POOLS["pool"]:
            _INDEX_CACHE[mode] = (codes, time.time())
            log.info("resolve_index_cache_updated", mode=mode, count=len(codes))
        return codes

    def _resolve_index(self, mode: str) -> List[str]:
        """从 Tushare index_weight 拉取动态成分股"""
        index_code, index_name = _INDEX_MAP[mode]
        try:
            import data_sources.tushare_source as tushare_module

            @tushare_module.with_tushare_retry(max_retries=2, delay=1.0)
            def _fetch():
                return self._ts.pro.index_weight(index_code=index_code)

            df = _fetch()
            if df is not None and not df.empty:
                latest_date = df["trade_date"].max()
                latest = df[df["trade_date"] == latest_date]
                codes = latest["con_code"].tolist()
                log.info("resolve_index", index=index_name, count=len(codes))
                return codes
        except Exception as e:
            log.error("resolve_index_failed", index=index_name, error=str(e))

        return self._resolve_pool_fallback()

    def _resolve_pool_fallback(self) -> List[str]:
        """pool 无 custom_codes 时：从本地 StockBasicInfo 取前20只活跃股票作为演示池"""
        try:
            from core.database import db_session
            from models.quant_data import StockBasicInfo
            with db_session() as db:
                rows = db.query(StockBasicInfo.code).filter(
                    StockBasicInfo.is_active == True
                ).limit(20).all()
                if rows:
                    codes = [r.code for r in rows]
                    log.info("resolve_pool_fallback", count=len(codes))
                    return codes
        except Exception as e:
            log.error("resolve_pool_fallback_failed", error=str(e))
        return ["600519.SH", "000001.SZ"]  # 最终兜底

    def _resolve_all(self) -> List[str]:
        """从本地 StockBasicInfo 表获取全市场"""
        try:
            from core.database import db_session
            from models.quant_data import StockBasicInfo

            with db_session() as db:
                rows = db.query(StockBasicInfo.code).filter(StockBasicInfo.is_active == True).all()
                if rows:
                    codes = [r.code for r in rows]
                    log.info("resolve_all", count=len(codes))
                    return codes
        except Exception as e:
            log.error("resolve_all_failed", error=str(e))

        return _STATIC_POOLS["pool"]

    @staticmethod
    def invalidate_cache(mode: str = None):
        """
        主动使缓存失效。
        mode=None 时清除所有宽基缓存（用于指数成分调整后强制重拉）。
        """
        if mode:
            _INDEX_CACHE.pop(mode, None)
            log.info("index_cache_invalidated", mode=mode)
        else:
            _INDEX_CACHE.clear()
            log.info("index_cache_cleared_all")
