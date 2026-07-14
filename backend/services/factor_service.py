"""
因子计算服务
============
FactorService 是唯一公开入口，保持向后兼容。
内部逻辑委托给 services.factors 子模块：
  - factors.calculator  : 单只因子计算（逐只慢路径）
  - factors.loader      : 批量 SQL 数据加载
  - factors.scoring     : 截面标准化 + 向量化打分 + IC 分析
  - factors.utils       : 工具函数
"""
import structlog
log = structlog.get_logger(__name__)

from typing import List, Dict, Any, Optional
import time
import numpy as np
import pandas as pd
from services.stock_service import StockService

# 导入子模块
from services.factors.utils import make_serializable, normalize_pct, robust_zscore
from services.factors.calculator import FACTOR_REGISTRY, get_factor_weights
from services.factors import loader as factor_loader
from services.factors import scoring as factor_scoring


class FactorService:
    """因子计算服务"""
    
    def __init__(self, stock_service: Optional[StockService] = None):
        self.stock_service = stock_service or StockService()
        
        self._PER_SOURCE_TIMEOUT = 5
        
        # 因子权重从 Registry 自动读取（声明式，无需手动维护）
        self.factor_weights = get_factor_weights()
    
    @staticmethod
    def normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
        """归一化权重并返回副本（不修改实例状态，线程安全）"""
        total = sum(weights.values())
        if total > 0:
            return {k: v / total for k, v in weights.items()}
        return dict(weights)

    def set_factor_weights(self, weights: Dict[str, float]):
        """[Deprecated] 修改实例权重，仅用于向后兼容"""
        self.factor_weights = self.normalize_weights(weights)
    
    # ── 向后兼容：静态方法代理 ──
    
    @staticmethod
    def _make_serializable(val):
        return make_serializable(val)
    
    @staticmethod
    def _normalize_pct(val):
        return normalize_pct(val)
    
    @staticmethod
    def _robust_zscore(values):
        return robust_zscore(values)
    
    # ── 通用因子调用（替代旧的每因子一个委托方法）──
    
    def _call_factor(self, name: str, **kwargs) -> Optional[float]:
        """通用因子调用：从 Registry 查找并执行"""
        entry = FACTOR_REGISTRY.get(name)
        if not entry:
            return None
        val = entry["fn"](**kwargs)
        # 防止 NaN/Inf 穿透到 JSON 序列化
        if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
            return None
        return float(val)

    # ── 截面标准化 ──

    def _cross_sectional_normalize(self, results, selected_factors):
        return factor_scoring.cross_sectional_normalize(
            results, self.factor_weights, selected_factors
        )
    
    def _calc_composite_score(self, factor_scores, selected_factors):
        return factor_scoring.calc_composite_score(
            factor_scores, selected_factors, self.factor_weights
        )

    # ── 批量数据加载 ──
    
    def _load_factor_df(self, codes, start_date, end_date):
        return factor_loader.load_factor_df(codes, start_date, end_date)
    
    # ── 向量化评分 ──

    def _score_factors_vectorized(self, df, selected_factors):
        return factor_scoring.score_factors_vectorized(
            df, selected_factors, self.factor_weights
        )

    def calculate_factor_scores_fast(
        self,
        codes: list,
        start_date: str,
        end_date: str,
        selected_factors: Optional[dict] = None,
        factor_weights: Optional[dict] = None,
    ) -> list:
        """
        向量化因子计算的公开入口（高性能版本）。
        仅包含本地 SQLite 数据，适合大批量（>50 只）快速筛选。
        """
        weights = factor_weights or self.factor_weights
        if selected_factors is None:
            selected_factors = {k: True for k in weights}

        t0 = time.time()
        df = self._load_factor_df(codes, start_date, end_date)
        log.warning(f"[FactorService][fast] 批量拉取 {len(codes)} 只数据耗时 {time.time()-t0:.2f}s")

        if df.empty:
            return []

        results = factor_scoring.score_factors_vectorized(df, selected_factors, weights)
        log.warning(f"[FactorService][fast] 向量化打分完成，耗时 {time.time()-t0:.2f}s")
        return results

    # ── IC 分析 ──

    def analyze_factor_ic(self, codes: list, start_date: str, end_date: str) -> dict:
        """因子绩效归因：优先滚动多截面 Forward IC，fallback 单截面"""
        try:
            # 优先：多截面滚动 IC（需要足够的历史数据）
            snapshots = factor_loader.load_monthly_snapshots(
                codes, start_date, end_date, periods=12
            )

            # 单截面作为 fallback 数据
            df = self._load_factor_df(codes, start_date, end_date)

            result = factor_scoring.analyze_factor_ic(
                df, self.factor_weights, snapshots=snapshots
            )
            if "error" not in result:
                result["date_range"] = f"{start_date} ~ {end_date}"
            return result
        except Exception as e:
            log.error(f"[FactorService] analyze_factor_ic error: {e}")
            return {"error": str(e)}

    # ── 行业分布 ──

    def get_industry_exposure(self, factor_results: List[Dict]) -> Dict[str, Any]:
        """获取行业分布"""
        industry_data = {}
        for stock in factor_results:
            industry = stock.get("industry", "未知")
            name = stock.get("name", stock.get("code", ""))
            key = industry if (industry and industry != "未知") else "其他"
            if key not in industry_data:
                industry_data[key] = []
            industry_data[key].append(name)
        
        sorted_items = sorted(industry_data.items(), key=lambda x: len(x[1]), reverse=True)
        return {k: {"count": len(v), "stocks": v} for k, v in sorted_items}

    # ── 逐只慢路径入口 ──

    def calculate_factors(
        self,
        stock_codes: List[str],
        start_date: str,
        end_date: str,
        selected_factors: Optional[Dict[str, bool]] = None,
    ) -> tuple:
        """
        逐只因子计算（慢路径），返回 (results, errors)。
        仅用于小规模（<50 只）精细化分析。
        """
        if selected_factors is None:
            selected_factors = {k: True for k in self.factor_weights}

        results = []
        errors = []
        
        for code in stock_codes:
            try:
                result = self._calculate_single_stock(code, start_date, end_date, selected_factors)
                if result:
                    results.append(result)
            except Exception as e:
                errors.append({"code": code, "error": str(e)})
        
        if results:
            results = self._cross_sectional_normalize(results, selected_factors)
            results.sort(key=lambda x: x.get("composite", 0), reverse=True)
        
        return results, errors

    def _calculate_single_stock(
        self,
        code: str,
        start_date: str,
        end_date: str,
        selected_factors: Dict[str, bool],
    ) -> Optional[Dict]:
        """计算单只股票的因子得分"""
        history = None
        ts_daily = None
        financial = None
        ak_sent = None
        
        # 获取历史数据
        try:
            history = self.stock_service.get_stock_history(code, start_date, end_date)
            if history is None or (hasattr(history, 'empty') and history.empty):
                return None
        except (AttributeError, TypeError):
            raise  # 代码 bug（方法不存在 / 类型错误），不能静默
        except Exception as e:
            log.warning("factor_history_load_failed", code=code, error=str(e))
        
        # 获取 Tushare 日线因子
        try:
            ts_daily = self.stock_service.get_tushare_daily_basic(code, end_date)
        except (AttributeError, TypeError):
            raise
        except Exception as e:
            log.warning("factor_ts_daily_load_failed", code=code, error=str(e))
        
        # 获取财务数据
        try:
            financial = self.stock_service.get_financial_data(code)
        except (AttributeError, TypeError):
            raise
        except Exception as e:
            log.warning("factor_financial_load_failed", code=code, error=str(e))
        
        # 注入股东户数变化率（concentration 因子需要，financial dict 不含此字段）
        # 浅拷贝避免污染 @cache_data 缓存
        if financial is not None:
            financial = dict(financial)
            try:
                from core.database import db_session
                from models.quant_data import StockShareholderCount
                from utils.asset_type import to_ts_code
                resolved_code = to_ts_code(code)
                with db_session() as db:
                    q = db.query(StockShareholderCount).filter(
                        StockShareholderCount.code == resolved_code
                    )
                    sh = q.order_by(StockShareholderCount.end_date.desc()).first()
                    if sh and sh.holder_num_change_rate is not None:
                        financial["holder_change_rate"] = float(sh.holder_num_change_rate)
            except Exception as e:
                log.debug("holder_change_rate_inject_failed", code=code, error=str(e))

        
        # 计算各因子
        factor_scores = {}
        raw_metrics = {}
        
        # 动态调用所有活跃因子（声明式，无需手动维护）
        for name in self.factor_weights:
            if not selected_factors.get(name, True):
                continue
            factor_scores[name] = self._call_factor(
                name,
                ts_daily=ts_daily,
                financial=financial,
                history=history,
                ak_sent=ak_sent,
            )
        
        # 收集更多原始指标
        if ts_daily:
            raw_metrics["pe_ttm"] = self._make_serializable(ts_daily.get("pe_ttm"))
            raw_metrics["pb"] = self._make_serializable(ts_daily.get("pb"))
            raw_metrics["turnover_rate"] = self._make_serializable(ts_daily.get("turnover_rate"))
            raw_metrics["total_mv"] = self._make_serializable(ts_daily.get("total_mv"))
        
        if financial:
            raw_metrics["roe"] = self._make_serializable(financial.get("roe"))
            raw_metrics["gross_profit_margin"] = self._make_serializable(financial.get("gross_profit_margin"))
            raw_metrics["revenue_yoy"] = self._make_serializable(financial.get("totaloperaterevenuetzyoy"))
        
        # 综合得分
        composite = self._calc_composite_score(factor_scores, selected_factors)
        
        # 获取股票名称和行业
        name = code
        industry = "未知"
        market_cap = 1.0
        try:
            info = self.stock_service.get_stock_info(code)
            if info:
                name = info.get("name", code)
                industry = info.get("industry", "未知")
        except (AttributeError, TypeError):
            raise
        except Exception as e:
            log.warning("factor_stock_info_failed", code=code, error=str(e))
        
        if ts_daily and ts_daily.get("total_mv"):
            market_cap = float(ts_daily["total_mv"])
        
        result = {
            "code": code,
            "name": name,
            "industry": industry,
            "market_cap": market_cap,
            "composite": composite,
            "raw_metrics": raw_metrics,
        }
        result.update(factor_scores)
        
        return result

    def _save_snapshot(self, results: list, trade_date: str):
        """将因子评分结果写入 factor_snapshot 表（每日信号使用）"""
        import json
        from core.database import db_session
        from models.quant_data import FactorSnapshot
        from sqlalchemy import text as _text

        td = pd.to_datetime(trade_date, errors="coerce")
        if pd.isna(td):
            return
        td_date = td.date()

        with db_session() as db:
            db.execute(_text(
                "DELETE FROM factor_snapshot WHERE trade_date = :td AND strategy_type = 'signal'"
            ), {"td": td_date})
            db.flush()

            records = []
            for rank_idx, r in enumerate(results, 1):
                records.append(FactorSnapshot(
                    code=r["code"],
                    trade_date=td_date,
                    strategy_type="signal",
                    composite=r.get("composite", 0.0),
                    rank=rank_idx,
                    factors_json=json.dumps({
                        k: r.get(k) for k in self.factor_weights
                        if k in r
                    }, ensure_ascii=False),
                ))
            if records:
                db.add_all(records)
                log.info("signal_snapshot_saved", count=len(records), date=str(td_date))

