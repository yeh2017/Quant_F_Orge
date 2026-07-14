"""放量突破策略"""

import numpy as np
from services.strategies.base import BaseStrategy, StrategyParam, sma


class VolumeBreakoutStrategy(BaseStrategy):
    id = "volume_breakout"
    name = "放量突破"
    desc = "价涨量增突破前高"
    detail = "N日最高价突破买入 | 成交量>均量M倍 | 跌破N日最低价止损"
    is_signal_based = True
    needs_volume = True  # 标记需要成交量数据

    def params_schema(self):
        return [
            StrategyParam("price_days", "价格突破周期", "int", 20, min=5, max=60, step=1),
            StrategyParam("vol_days", "均量周期", "int", 10, min=5, max=30, step=1),
            StrategyParam("vol_ratio", "放量倍数", "float", 1.5, min=1.0, max=3.0, step=0.1),
        ]

    def generate_signals(self, prices, params, volume=None):
        price_days = params.get("price_days", 20)
        vol_days = params.get("vol_days", 10)
        vol_ratio = params.get("vol_ratio", 1.5)

        T, N = prices.shape
        signals = np.zeros((T, N))

        # 均量（如果无成交量数据则退化为纯价格突破）
        has_vol = volume is not None and volume.shape == prices.shape
        if has_vol:
            avg_vol = sma(volume, vol_days)
        else:
            import structlog
            structlog.get_logger("strategy").warning(
                "volume_breakout_no_volume",
                msg="无成交量数据，退化为纯价格突破策略",
            )

        for t in range(price_days, T):
            window = prices[t - price_days:t]
            high_n = np.nanmax(window, axis=0)  # N日最高价
            low_n = np.nanmin(window, axis=0)   # N日最低价

            # 买入：突破N日最高价
            breakout = prices[t] > high_n
            if has_vol:
                # 且成交量 > 均量 * 倍数
                vol_ok = ~np.isnan(avg_vol[t]) & (volume[t] > avg_vol[t] * vol_ratio)
                buy = breakout & vol_ok
            else:
                buy = breakout

            # 卖出：跌破N日最低价
            sell = prices[t] < low_n

            signals[t][buy] = 1
            signals[t][sell] = -1

        return signals
