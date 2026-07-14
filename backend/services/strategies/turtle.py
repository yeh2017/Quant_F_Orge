"""海龟交易策略"""

import numpy as np
from services.strategies.base import BaseStrategy, StrategyParam


class TurtleStrategy(BaseStrategy):
    id = "turtle"
    name = "海龟交易"
    desc = "唐奇安通道趋势突破"
    detail = "突破N日最高价买入 | 跌破M日最低价卖出 | 经典趋势跟踪"
    is_signal_based = True

    def params_schema(self):
        return [
            StrategyParam("entry", "入场周期", "int", 20, min=10, max=55, step=1),
            StrategyParam("exit", "出场周期", "int", 10, min=5, max=30, step=1),
        ]

    def generate_signals(self, prices, params, volume=None):
        entry = params.get("entry", 20)
        exit_n = params.get("exit", 10)

        T, N = prices.shape
        signals = np.zeros((T, N))

        for t in range(entry, T):
            high_n = np.nanmax(prices[t - entry:t], axis=0)
            low_m = np.nanmin(prices[max(0, t - exit_n):t], axis=0)
            signals[t][prices[t] > high_n] = 1
            signals[t][prices[t] < low_m] = -1
        return signals
