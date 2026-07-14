"""布林带回归策略"""

import numpy as np
from services.strategies.base import BaseStrategy, StrategyParam, sma


class BbandStrategy(BaseStrategy):
    id = "bband"
    name = "布林带回归"
    desc = "超卖买入超买卖出"
    detail = "跌破下轨买入 | 突破上轨卖出 | 均值回归策略"
    is_signal_based = True

    def params_schema(self):
        return [
            StrategyParam("window", "均线周期", "int", 20, min=10, max=60, step=1),
            StrategyParam("num_std", "标准差倍数", "float", 2.0, min=1.0, max=3.0, step=0.1),
        ]

    def generate_signals(self, prices, params, volume=None):
        window = params.get("window", 20)
        num_std = params.get("num_std", 2.0)

        T, N = prices.shape
        signals = np.zeros((T, N))
        mid = sma(prices, window)

        std = np.full_like(prices, np.nan)
        for t in range(window - 1, T):
            std[t] = np.nanstd(prices[t - window + 1:t + 1], axis=0)

        upper = mid + num_std * std
        lower = mid - num_std * std

        for t in range(1, T):
            valid = ~np.isnan(lower[t]) & ~np.isnan(upper[t])
            buy = valid & (prices[t] <= lower[t]) & (prices[t - 1] > lower[t - 1])
            sell = valid & (prices[t] >= upper[t]) & (prices[t - 1] < upper[t - 1])
            signals[t][buy] = 1
            signals[t][sell] = -1
        return signals
