"""
仓位管理层
===========
信号矩阵 → 权重矩阵。统一处理：
- 等权 / 因子加权
- 涨跌停过滤
- 换手成本计算
"""

import numpy as np
from typing import Dict, List


class PositionManager:
    """信号/因子 → 持仓权重"""

    def __init__(self, commission: float = 0.0003, stamp_tax: float = 0.001,
                 slippage: float = 0.001,
                 limit_up: float = 0.095, limit_down: float = -0.095):
        self.commission = commission
        self.stamp_tax = stamp_tax
        self.slippage = slippage
        self.limit_up = limit_up
        self.limit_down = limit_down

    def signals_to_weights_daily(
        self, signals: np.ndarray, holding: np.ndarray,
        allow_reentry: bool = False,
    ) -> tuple[np.ndarray, bool]:
        """
        信号驱动：逐日更新持仓。

        Args:
            signals: (N,) 当日信号 +1/-1/0
            holding: (N,) 当前持仓状态 bool
            allow_reentry: 允许对已持仓标的重复发信号（网格等加减仓策略）

        Returns:
            (weights, changed): 新权重向量和是否有变化
        """
        if allow_reentry:
            # 网格模式：买/卖信号不受持仓状态限制
            buy_mask = signals > 0
            sell_mask = signals < 0
        else:
            # 二元模式（MACD/布林带等）：只在未持仓时买、已持仓时卖
            buy_mask = (signals > 0) & ~holding
            sell_mask = (signals < 0) & holding

        if not np.any(buy_mask) and not np.any(sell_mask):
            return None, False

        holding[buy_mask] = True
        holding[sell_mask] = False
        n_hold = int(holding.sum())
        weights = np.where(holding, 1.0 / max(n_hold, 1), 0.0)
        return weights, True

    def factor_to_weights(
        self,
        codes: List[str],
        factor_scores: Dict[str, float],
        top_n: int,
        strategy_type: str,
        as_of_date: str = None,
        max_single_weight: float = None,
    ) -> np.ndarray:
        """
        因子驱动：按评分选 TopN，计算持仓权重。

        对 double_low_cb，从 ConvertibleBondFactor 表读取双低分倒数加权。
        对 multifactor/convertible，按因子评分比例加权。
        max_single_weight: 单只股票最大权重（如 0.30=30%），None=不限。
        """
        n = len(codes)
        w = np.zeros(n)

        if strategy_type == "double_low_cb":
            return self._double_low_weights(codes, as_of_date)

        if factor_scores:
            score_arr = np.array([factor_scores.get(c, 0.5) for c in codes])
            ranked = np.argsort(-score_arr)[:top_n]
            raw = score_arr[ranked]
            total = raw.sum()
            if total > 0:
                w[ranked] = raw / total
            else:
                w[ranked] = 1.0 / top_n
        else:
            k = min(top_n, n)
            w[:k] = 1.0 / k

        # 权重裁剪：仅当显式设置且持仓数足够时生效
        if max_single_weight and max_single_weight > 0:
            active = int((w > 0).sum())
            min_stocks = int(1.0 / max_single_weight) + 1
            if active >= min_stocks:
                w = self._apply_weight_cap(w, max_single_weight)

        return w

    def apply_limits(
        self, weights: np.ndarray, current_weights: np.ndarray,
        day_returns: np.ndarray
    ) -> np.ndarray:
        """涨跌停过滤 + 归一化"""
        n = len(weights)
        for idx in range(n):
            if weights[idx] > 0 and current_weights[idx] == 0:
                if day_returns[idx] > self.limit_up:
                    weights[idx] = 0  # 涨停买不进
            elif weights[idx] == 0 and current_weights[idx] > 0:
                if day_returns[idx] < self.limit_down:
                    weights[idx] = current_weights[idx]  # 跌停卖不掉

        if weights.sum() > 0:
            weights = weights / weights.sum()
        return weights

    def calc_cost(self, current_weights: np.ndarray, new_weights: np.ndarray) -> float:
        """计算换手成本（佣金 + 印花税 + 滑点）"""
        sell_turnover = np.sum(np.maximum(current_weights - new_weights, 0))
        buy_turnover = np.sum(np.maximum(new_weights - current_weights, 0))
        total_turnover = buy_turnover + sell_turnover
        return (buy_turnover * self.commission
                + sell_turnover * (self.commission + self.stamp_tax)
                + total_turnover * self.slippage)

    @staticmethod
    def _apply_weight_cap(weights: np.ndarray, max_weight: float = 0.30) -> np.ndarray:
        """迭代裁剪法：超限权重截断后重新分配至未超限股票（仅在非零权重间操作）"""
        w = weights.copy()
        # 只对有持仓的位置做裁剪，零权重不参与
        active_mask = w > 0
        if active_mask.sum() == 0:
            return w
        for _ in range(10):
            active_total = w[active_mask].sum()
            if active_total <= 0:
                w[active_mask] = 1.0 / active_mask.sum()
                return w
            # 归一化（仅 active 部分）
            w[active_mask] = w[active_mask] / active_total
            capped = False
            excess = 0.0
            uncapped_count = 0
            for i in range(len(w)):
                if not active_mask[i]:
                    continue
                if w[i] > max_weight:
                    excess += w[i] - max_weight
                    w[i] = max_weight
                    capped = True
                else:
                    uncapped_count += 1
            if not capped or uncapped_count == 0:
                break
            add_per = excess / uncapped_count
            for i in range(len(w)):
                if active_mask[i] and w[i] < max_weight:
                    w[i] += add_per
        return w

    @staticmethod
    def _double_low_weights(codes: List[str], as_of_date: str = None) -> np.ndarray:
        """从 ConvertibleBondFactor 表读双低分，倒数加权
        
        as_of_date: 截止日期，避免使用未来数据。None 时取最新。
        """
        n = len(codes)
        w = np.zeros(n)
        try:
            from core.database import db_session
            from models.quant_data import ConvertibleBondFactor as CBF

            with db_session() as db:
                from sqlalchemy import func
                q = db.query(func.max(CBF.trade_date))
                if as_of_date:
                    q = q.filter(CBF.trade_date <= as_of_date)
                latest = q.scalar()
                if not latest:
                    return np.ones(n) / n

                rows = db.query(CBF.code, CBF.double_low_score).filter(
                    CBF.trade_date == latest,
                    CBF.code.in_(codes),
                    CBF.double_low_score.isnot(None),
                ).all()

                score_map = {r.code: float(r.double_low_score) for r in rows}
                for i, c in enumerate(codes):
                    dl = score_map.get(c)
                    if dl and dl > 0:
                        w[i] = 1.0 / dl  # 双低分越小越好
        except (AttributeError, TypeError):
            raise
        except Exception:
            w = np.ones(n) / n

        total = w.sum()
        return w / total if total > 0 else np.ones(n) / n
