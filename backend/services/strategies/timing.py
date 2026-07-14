"""均线择时策略（含回踩模式）"""

import numpy as np
from services.strategies.base import BaseStrategy, StrategyParam, sma


class TimingStrategy(BaseStrategy):
    id = "timing"
    name = "均线择时"
    desc = "MA快慢线趋势判断 / 回踩买入"
    detail = "金叉模式: 快线上穿慢线买入 | 回踩模式: 趋势中回踩短均线买入"
    is_signal_based = True

    def params_schema(self):
        return [
            StrategyParam("mode", "信号模式", "select", "crossover",
                          options=[
                              {"value": "crossover", "label": "金叉/死叉"},
                              {"value": "pullback", "label": "回踩买入"},
                          ]),
            StrategyParam("fast_ma", "快线周期", "int", 20, min=5, max=60, step=1),
            StrategyParam("slow_ma", "慢线周期", "int", 60, min=20, max=120, step=1),
            StrategyParam("threshold", "回踩阈值(%)", "float", 1.5, min=0.5, max=3.0, step=0.1),
        ]

    def generate_signals(self, prices, params, volume=None):
        mode = params.get("mode", "crossover")
        fast = params.get("fast_ma", 20)
        slow = params.get("slow_ma", 60)

        T, N = prices.shape
        signals = np.zeros((T, N))
        ma_fast = sma(prices, fast)
        ma_slow = sma(prices, slow)

        if mode == "pullback":
            thresh = params.get("threshold", 1.5) / 100.0
            for t in range(1, T):
                valid = ~np.isnan(ma_fast[t]) & ~np.isnan(ma_slow[t])
                uptrend = valid & (ma_fast[t] > ma_slow[t])
                near = np.abs(prices[t] - ma_fast[t]) / (ma_fast[t] + 1e-9) < thresh
                was_above = prices[t - 1] > ma_fast[t - 1]
                buy = uptrend & near & was_above
                sell = valid & (prices[t] < ma_slow[t]) & (prices[t - 1] >= ma_slow[t - 1])
                signals[t][buy] = 1
                signals[t][sell] = -1
        else:
            for t in range(1, T):
                valid = ~np.isnan(ma_fast[t]) & ~np.isnan(ma_slow[t])
                cross_up = valid & (ma_fast[t] > ma_slow[t]) & (ma_fast[t - 1] <= ma_slow[t - 1])
                cross_down = valid & (ma_fast[t] < ma_slow[t]) & (ma_fast[t - 1] >= ma_slow[t - 1])
                signals[t][cross_up] = 1
                signals[t][cross_down] = -1
        return signals
