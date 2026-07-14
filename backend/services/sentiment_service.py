"""
情绪因子服务
============
从 stock_service.py 提取的情绪面/另类因子聚合逻辑。

数据源优先级: 本地 DB → Tushare API → AkShare 兜底
"""

import pandas as pd
import structlog
from typing import Optional, Dict, Any

from utils.cache_manager import cache_data

log = structlog.get_logger(__name__)


class SentimentService:
    """情绪面因子聚合（资金流向 + 盈利预测）"""

    def __init__(self, sources: Dict):
        """
        Args:
            sources: StockService._sources 数据源字典
        """
        self._sources = sources

    @cache_data(expire_days=7)
    def get_akshare_market_forecast(self) -> Optional[pd.DataFrame]:
        """获取全市场机构盈利预测数据"""
        try:
            if "akshare" not in self._sources:
                return None
            ak = self._sources["akshare"].ak
            df = ak.stock_profit_forecast_em()
            return df
        except Exception as e:
            log.warning("akshare_market_forecast_error", error=str(e))
            return None

    @cache_data(expire_days=7)
    def get_tushare_forecast(self, code: str) -> Optional[Dict[str, Any]]:
        """获取业绩预告数据 (120积分可用)"""
        try:
            if "tushare" not in self._sources:
                return None
            ts_source = self._sources["tushare"]
            if not ts_source._is_api_available("forecast"):
                return None
            ts_code = ts_source._format_ts_code(code)

            import data_sources.tushare_source as tushare_module
            @tushare_module.with_tushare_retry(max_retries=2, delay=1.0)
            def _fetch():
                return ts_source.pro.forecast(ts_code=ts_code)

            df = _fetch()
            if df is not None and not df.empty:
                latest = df.sort_values("ann_date", ascending=False).iloc[0]
                return {
                    "type": latest.get("type", ""),
                    "net_profit_min": latest.get("net_profit_min"),
                    "net_profit_max": latest.get("net_profit_max"),
                    "change_reason": latest.get("change_reason", ""),
                    "last_parent_net": latest.get("last_parent_net"),
                }
            return None
        except Exception as e:
            log.warning("tushare_forecast_error", error=str(e))
            return None

    @cache_data(expire_days=1)
    def get_tushare_moneyflow(self, code: str, days: int = 3) -> Optional[Dict[str, Any]]:
        """获取个股资金流向 (2000积分可用)"""
        try:
            if "tushare" not in self._sources:
                return None
            ts_source = self._sources["tushare"]
            if not ts_source._is_api_available("moneyflow"):
                return None
            ts_code = ts_source._format_ts_code(code)

            import data_sources.tushare_source as tushare_module
            @tushare_module.with_tushare_retry(max_retries=2, delay=1.0)
            def _fetch():
                return ts_source.pro.moneyflow(ts_code=ts_code, limit=days)

            mf_df = _fetch()
            if mf_df is not None and not mf_df.empty:
                result = {}
                if 'buy_lg_amount' in mf_df.columns and 'sell_lg_amount' in mf_df.columns:
                    net_flow = (mf_df['buy_lg_amount'] - mf_df['sell_lg_amount']).mean()
                    total_flow = (mf_df['buy_lg_amount'] + mf_df['sell_lg_amount']).mean()
                    if total_flow > 0:
                        result["net_inflow_ratio"] = float(net_flow / total_flow * 100)
                if 'buy_md_amount' in mf_df.columns:
                    result["buy_lg_amount"] = float(mf_df['buy_lg_amount'].mean())
                    result["sell_lg_amount"] = float(mf_df['sell_lg_amount'].mean())
                return result if result else None
            return None
        except Exception as e:
            err_str = str(e)
            if "权限" in err_str or "积分" in err_str:
                ts_source._mark_api_unavailable("moneyflow", err_str)
            log.warning("moneyflow_tushare_failed", error=str(e))
            return None

    @cache_data(expire_days=1)
    def get_sentiment_factors(self, code: str) -> Optional[Dict[str, Any]]:
        """
        情绪面因子聚合入口。
        降级链: 本地 DB → Tushare moneyflow → AkShare → Tushare forecast → AkShare forecast
        """
        result = {}
        ts_source = self._sources.get("tushare")
        ak = self._sources.get("akshare")

        # ---- 1. 资金流向（本地 DB 优先）----
        try:
            from core.database import db_session
            from models.quant_data import StockMoneyFlow
            with db_session() as db:
                row = db.query(StockMoneyFlow).filter(
                    StockMoneyFlow.code == code
                ).order_by(StockMoneyFlow.trade_date.desc()).first()
                if row and row.net_mf_amount is not None:
                    result["net_inflow_ratio"] = float(row.net_mf_amount)
        except (AttributeError, TypeError):
            raise
        except Exception as e:
            log.warning("moneyflow_local_db_failed", code=code, error=str(e))

        # ---- 1b. 资金流向（Tushare API 次选）----
        if "net_inflow_ratio" not in result and ts_source:
            try:
                mf = self.get_tushare_moneyflow(code, days=3)
                if mf:
                    result.update(mf)
            except (AttributeError, TypeError):
                raise
            except Exception as e:
                log.warning("moneyflow_tushare_fallback_failed", code=code, error=str(e))

        # ---- 1c. 资金流向（AkShare 兜底）----
        if "net_inflow_ratio" not in result and ak:
            try:
                flow_df = ak.ak.stock_individual_fund_flow(stock=code)
                if flow_df is not None and len(flow_df) >= 3:
                    recent = flow_df.tail(3)
                    ratio_cols = [c for c in flow_df.columns
                                  if '主力净流入' in c and ('占比' in c or '净占' in c)]
                    if ratio_cols:
                        vals = pd.to_numeric(
                            recent[ratio_cols[0]].astype(str).str.replace('%', ''),
                            errors='coerce'
                        ).fillna(0)
                        result["net_inflow_ratio"] = float(vals.mean())
            except (AttributeError, TypeError):
                raise
            except Exception as e:
                log.warning("moneyflow_akshare_fallback_failed", code=code, error=str(e))

        # ---- 2. 机构盈利预测（Tushare forecast 主力）----
        try:
            forecast = self.get_tushare_forecast(code)
            if forecast:
                result["forecast"] = forecast
        except (AttributeError, TypeError):
            raise
        except Exception as e:
            log.warning("forecast_tushare_failed", code=code, error=str(e))

        # ---- 2b. 盈利预测（AkShare 全市场缓存兜底）----
        if "forecast" not in result and ak:
            try:
                forecast_df = self.get_akshare_market_forecast()
                if forecast_df is not None and not forecast_df.empty:
                    stock_fc = forecast_df[forecast_df["代码"] == code]
                    if not stock_fc.empty:
                        result["forecast_rating"] = stock_fc.iloc[0].to_dict()
            except (AttributeError, TypeError):
                raise
            except Exception as e:
                log.warning("forecast_akshare_fallback_failed", code=code, error=str(e))

        return result if result else None
