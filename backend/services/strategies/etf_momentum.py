"""ETF 动量轮动策略"""

import numpy as np
from services.strategies.base import BaseStrategy, StrategyParam


class EtfMomentumStrategy(BaseStrategy):
    id = "etf_momentum"
    name = "ETF动量轮动"
    desc = "持有近期涨幅最强的ETF"
    detail = "按N日收益率排序 | 持有TopK个ETF | 定期轮换弱势标的"
    is_signal_based = False
    needs_factor = False  # 不依赖 FactorService，自行从价格矩阵算动量分

    def params_schema(self):
        return [
            StrategyParam("lookback_days", "动量回看天数", "int", 20,
                          min=5, max=120, step=5),
            StrategyParam("top_n", "持仓数量", "int", 3,
                          min=1, max=10, step=1),
            StrategyParam("skip_days", "跳过近N天", "int", 0,
                          min=0, max=10, step=1),
            StrategyParam("rebalance", "调仓周期", "select", "weekly",
                          options=[
                              {"value": "weekly", "label": "每周"},
                              {"value": "monthly", "label": "每月"},
                          ]),
        ]

    def generate_signals(self, prices, params, volume=None):
        # 因子策略不需要信号矩阵
        return np.zeros_like(prices)

    def compute_factor_scores(self, codes, price_arr, dates, params):
        """
        自计算动量因子分：N日收益率作为排名依据。

        Args:
            codes: 标的代码列表
            price_arr: (T, N) 收盘价矩阵（截至当前日）
            dates: 日期列表（截至当前日）
            params: 策略参数

        Returns:
            {code: score} 动量得分（越高越强）
        """
        lookback = params.get("lookback_days", 20)
        skip = params.get("skip_days", 0)

        T = len(price_arr)
        end = T - skip if skip > 0 else T
        start = end - lookback

        if start < 0 or end <= start:
            return {}

        p_start = price_arr[start]
        p_end = price_arr[end - 1]

        # 动量 = (end - start) / start，加 1 确保非负（用于比例加权）
        scores = {}
        for i, code in enumerate(codes):
            if p_start[i] > 0 and not np.isnan(p_end[i]):
                momentum = (p_end[i] - p_start[i]) / p_start[i]
                scores[code] = float(1.0 + momentum)  # 保证正数，便于比例加权
        return scores
