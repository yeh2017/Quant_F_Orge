"""可转债双低策略"""

import numpy as np
from services.strategies.base import BaseStrategy, StrategyParam


class DoubleLowCbStrategy(BaseStrategy):
    id = "double_low_cb"
    name = "可转债双低"
    desc = "双低分月度轮动"
    detail = "双低分 = 转债价格 + 溢价率 | 月度调仓 | 仅限可转债标的"
    is_signal_based = False
    needs_factor = False  # 使用 ConvertibleBondFactor 表而非通用因子

    def params_schema(self):
        return [
            StrategyParam("top_n", "持仓数量", "int", 5, min=1, max=20, step=1),
            StrategyParam("rebalance", "调仓周期", "select", "monthly",
                          options=[
                              {"value": "weekly", "label": "每周"},
                              {"value": "monthly", "label": "每月"},
                          ]),
        ]

    def generate_signals(self, prices, params, volume=None):
        return np.zeros_like(prices)
