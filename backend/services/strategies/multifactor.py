"""多因子选股策略（含纯估值模式）"""

import numpy as np
from services.strategies.base import BaseStrategy, StrategyParam


class MultifactorStrategy(BaseStrategy):
    id = "multifactor"
    name = "因子选股"
    desc = "多因子复合 / 纯低估值"
    detail = "复合模式: 价值+质量+动量多维打分 | 估值模式: 纯PE/PB最低排名 | 下拉切换"
    is_signal_based = False
    needs_factor = True

    # 估值模式的因子配置（仅 value=True，其余活跃因子显式关闭）
    _VALUE_ONLY_FACTORS = {
        "reversal": False,
        "value": True,
        "quality": False,
        "size": False,
        "momentum": False,
        "lowvol": False,
        "growth": False,
        "dividend": False,
        "concentration": False,
        "leverage": False,
    }

    def params_schema(self):
        return [
            StrategyParam("mode", "选股模式", "select", "composite",
                          options=[
                              {"value": "composite", "label": "多因子复合"},
                              {"value": "value_only", "label": "纯低估值"},
                          ]),
            StrategyParam("top_n", "持仓数量", "int", 5, min=1, max=20, step=1),
            StrategyParam("rebalance", "调仓周期", "select", "monthly",
                          options=[
                              {"value": "weekly", "label": "每周"},
                              {"value": "monthly", "label": "每月"},
                              {"value": "quarterly", "label": "每季"},
                          ]),
        ]

    @property
    def default_factors(self):
        """动态返回——仅在估值模式时覆盖因子选择"""
        return None  # 由回测入口根据 strategy_params 动态决定

    def get_factor_override(self, strategy_params: dict):
        """根据 mode 参数返回因子覆盖配置"""
        if strategy_params.get("mode") == "value_only":
            return self._VALUE_ONLY_FACTORS
        return None

    def generate_signals(self, prices, params, volume=None):
        # 因子策略不生成信号矩阵
        return np.zeros_like(prices)
