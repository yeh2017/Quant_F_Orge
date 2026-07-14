"""网格交易策略 — 震荡市高抛低吸"""

import numpy as np
from services.strategies.base import BaseStrategy, StrategyParam, sma


class GridStrategy(BaseStrategy):
    id = "grid"
    name = "网格交易"
    desc = "震荡区间内分批高抛低吸"
    detail = "以均线为中轴，按固定间距设置网格 | 每跌一格加仓 | 每涨一格减仓"
    is_signal_based = True
    allow_reentry = True

    def params_schema(self):
        return [
            StrategyParam("ma_window", "中轴均线周期", "int", 20, min=5, max=60, step=1),
            StrategyParam("grid_pct", "网格间距(%)", "float", 3.0, min=1.0, max=10.0, step=0.5),
            StrategyParam("num_grids", "网格层数", "int", 4, min=2, max=8, step=1),
        ]

    def generate_signals(self, prices, params, volume=None):
        """
        网格逻辑：
        - 中轴 = MA(ma_window)
        - 从中轴向下每隔 grid_pct% 设一条买入线（共 num_grids 层）
        - 从中轴向上每隔 grid_pct% 设一条卖出线（共 num_grids 层）
        - 价格从上方穿越买入线 → +1（买入信号强度与层数成正比）
        - 价格从下方穿越卖出线 → -1
        """
        ma_window = params.get("ma_window", 20)
        grid_pct = params.get("grid_pct", 3.0) / 100.0
        num_grids = params.get("num_grids", 4)

        T, N = prices.shape
        signals = np.zeros((T, N))
        mid = sma(prices, ma_window)

        for t in range(1, T):
            valid = ~np.isnan(mid[t]) & ~np.isnan(mid[t - 1])
            if not np.any(valid):
                continue

            for g in range(1, num_grids + 1):
                # 买入网格线：中轴下方 g * grid_pct
                buy_line = mid[t] * (1 - g * grid_pct)
                buy_line_prev = mid[t - 1] * (1 - g * grid_pct)
                # 价格从上方跌破该网格线 → 买入
                cross_down = valid & (prices[t] <= buy_line) & (prices[t - 1] > buy_line_prev)
                signals[t][cross_down] = 1

                # 卖出网格线：中轴上方 g * grid_pct
                sell_line = mid[t] * (1 + g * grid_pct)
                sell_line_prev = mid[t - 1] * (1 + g * grid_pct)
                # 价格从下方突破该网格线 → 卖出
                cross_up = valid & (prices[t] >= sell_line) & (prices[t - 1] < sell_line_prev)
                signals[t][cross_up] = -1

        return signals
