"""
动态标的池提供者
================
为回测引擎提供按日期动态变化的标的池。

三种实现:
  - CustomPoolUniverse:    固定池（向后兼容）
  - FactorFilterUniverse:  因子筛选（每个调仓日按阈值动态选股）
  - FullMarketUniverse:    全市场（回测期间所有上市股票）

使用方式:
  provider = create_provider({"type": "factor_filter", "filters": {"pe_ttm_max": 30}})
  codes = provider.get_codes("2024-03-01")

注: 前端镜像逻辑位于 StrategyBacktestPanel.jsx 的标的来源选择器
"""
import structlog
from abc import ABC, abstractmethod
from typing import List, Dict, Any

log = structlog.get_logger(__name__)


class UniverseProvider(ABC):
    """标的池提供者基类"""

    @abstractmethod
    def get_codes(self, date: str) -> List[str]:
        """返回指定日期的标的列表"""
        ...


class CustomPoolUniverse(UniverseProvider):
    """固定池：直接使用传入的 codes，向后兼容"""

    def __init__(self, codes: List[str]):
        self.codes = codes

    def get_codes(self, date: str) -> List[str]:
        return self.codes


class FactorFilterUniverse(UniverseProvider):
    """因子筛选池：每个调仓日从 stock_daily_factors 按阈值动态选股

    支持的 filters:
      pe_ttm_max:    市盈率上限
      pe_ttm_min:    市盈率下限
      pb_max:        市净率上限
      pb_min:        市净率下限
      total_mv_min:  总市值下限（万元）
      total_mv_max:  总市值上限（万元）
      dv_ratio_min:  股息率下限（%）
      industry:      行业名称（精确匹配）
    """

    # 因子字段 → (StockDailyFactor 列名, 比较方向)
    _FILTER_MAP = {
        "pe_ttm_max":   ("pe_ttm",   "<="),
        "pe_ttm_min":   ("pe_ttm",   ">="),
        "pb_max":       ("pb",       "<="),
        "pb_min":       ("pb",       ">="),
        "total_mv_min": ("total_mv", ">="),
        "total_mv_max": ("total_mv", "<="),
        "dv_ratio_min": ("dv_ratio", ">="),
    }

    def __init__(self, filters: Dict[str, Any]):
        self.filters = filters
        self._cache: Dict[str, List[str]] = {}

    def get_codes(self, date: str) -> List[str]:
        if date in self._cache:
            return self._cache[date]

        from core.database import db_session
        from models.quant_data import StockDailyFactor
        from sqlalchemy import func

        with db_session() as db:
            # 找到 <= date 的最近因子日（因子不一定每天都有）
            latest = (
                db.query(func.max(StockDailyFactor.trade_date))
                .filter(StockDailyFactor.trade_date <= date)
                .scalar()
            )
            if not latest:
                log.warning("factor_filter_no_data", date=date)
                self._cache[date] = []
                return []

            q = db.query(StockDailyFactor.code).filter(
                StockDailyFactor.trade_date == latest,
                # 排除北交所（4/8/9开头）：流动性差 + 涨跌停30%与回测引擎不匹配
                ~StockDailyFactor.code.like("4%"),
                ~StockDailyFactor.code.like("8%"),
                ~StockDailyFactor.code.like("9%"),
            )

            # 动态拼接过滤条件
            for key, value in self.filters.items():
                if key in ("industry", "top_n"):
                    continue  # 行业过滤走 StockBasicInfo，top_n 后处理
                spec = self._FILTER_MAP.get(key)
                if not spec:
                    continue
                col_name, op = spec
                col = getattr(StockDailyFactor, col_name, None)
                if col is None:
                    continue
                if op == "<=":
                    q = q.filter(col <= value)
                elif op == ">=":
                    q = q.filter(col >= value)

            # 按市值倒序排序（截断交给 backtest_service._resolve_universe）
            q = q.order_by(StockDailyFactor.total_mv.desc())

            codes = [r[0] for r in q.all()]

            # 行业过滤（双体系：Tushare sub + 申万 L1）
            industry = self.filters.get("industry")
            if industry and codes:
                from utils.industry import get_industry_codes
                industry_codes = get_industry_codes(db, industry)
                codes = [c for c in codes if c in industry_codes]

        log.info("factor_filter_result", date=date, factor_date=str(latest), count=len(codes))
        self._cache[date] = codes
        return codes


class FullMarketUniverse(UniverseProvider):
    """全市场：当前所有在市股票"""

    def __init__(self):
        self._cache: Dict[str, List[str]] = {}

    def get_codes(self, date: str) -> List[str]:
        if date in self._cache:
            return self._cache[date]

        from core.database import db_session
        from models.quant_data import StockBasicInfo

        # list_date 存为 "YYYY-MM-DD"，date 入参也是 ISO 格式，直接字符串比较
        with db_session() as db:
            codes = [
                r[0] for r in
                db.query(StockBasicInfo.code)
                .filter(
                    StockBasicInfo.list_date <= date,
                    StockBasicInfo.is_active == True,
                    # 排除北交所（4/8/9开头）：流动性差 + 涨跌停30%与回测引擎不匹配
                    ~StockBasicInfo.code.like("4%"),
                    ~StockBasicInfo.code.like("8%"),
                    ~StockBasicInfo.code.like("9%"),
                )
                .all()
            ]

        log.info("full_market_result", date=date, count=len(codes))
        self._cache[date] = codes
        return codes


def create_provider(config: Dict[str, Any]) -> UniverseProvider:
    """工厂函数：根据配置创建对应的 Provider"""
    provider_type = config.get("type", "custom")

    if provider_type == "custom":
        codes = config.get("codes", [])
        return CustomPoolUniverse(codes)
    elif provider_type == "factor_filter":
        filters = config.get("filters", {})
        if not filters:
            raise ValueError("factor_filter 类型必须提供 filters 参数")
        return FactorFilterUniverse(filters)
    elif provider_type == "full_market":
        return FullMarketUniverse()
    else:
        raise ValueError(f"未知的标的池类型: {provider_type}")
