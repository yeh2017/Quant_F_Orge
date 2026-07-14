"""动量指标策略（MACD / RSI 双模式）"""

import numpy as np
from services.strategies.base import BaseStrategy, StrategyParam, ema


class MacdStrategy(BaseStrategy):
    id = "macd"
    name = "动量指标"
    desc = "MACD趋势 / RSI超买超卖"
    detail = "MACD模式: DIF上穿DEA做多 | RSI模式: 超卖买入超买卖出 | 下拉切换"
    is_signal_based = True

    def params_schema(self):
        return [
            StrategyParam("mode", "指标模式", "select", "macd",
                          options=[
                              {"value": "macd", "label": "MACD金叉/死叉"},
                              {"value": "rsi", "label": "RSI超买超卖"},
                          ]),
            StrategyParam("fast", "MACD快线", "int", 12, min=5, max=30, step=1),
            StrategyParam("slow", "MACD慢线", "int", 26, min=15, max=60, step=1),
            StrategyParam("signal", "MACD信号线", "int", 9, min=3, max=20, step=1),
            StrategyParam("rsi_period", "RSI周期", "int", 14, min=5, max=30, step=1),
            StrategyParam("rsi_oversold", "RSI超卖线", "int", 30, min=10, max=40, step=5),
            StrategyParam("rsi_overbought", "RSI超买线", "int", 70, min=60, max=90, step=5),
        ]

    def generate_signals(self, prices, params, volume=None):
        mode = params.get("mode", "macd")
        T, N = prices.shape
        signals = np.zeros((T, N))

        if mode == "rsi":
            return self._rsi_signals(prices, params, T, N, signals)
        else:
            return self._macd_signals(prices, params, T, N, signals)

    @staticmethod
    def _macd_signals(prices, params, T, N, signals):
        fast = params.get("fast", 12)
        slow = params.get("slow", 26)
        signal = params.get("signal", 9)

        ema_fast = ema(prices, fast)
        ema_slow = ema(prices, slow)
        dif = ema_fast - ema_slow
        dea = ema(dif, signal)

        for t in range(1, T):
            cross_up = (dif[t] > dea[t]) & (dif[t - 1] <= dea[t - 1])
            cross_down = (dif[t] < dea[t]) & (dif[t - 1] >= dea[t - 1])
            signals[t][cross_up] = 1
            signals[t][cross_down] = -1
        return signals

    @staticmethod
    def _rsi_signals(prices, params, T, N, signals):
        """RSI 超买超卖信号"""
        period = params.get("rsi_period", 14)
        oversold = params.get("rsi_oversold", 30)
        overbought = params.get("rsi_overbought", 70)

        # 计算 RSI（矩阵化）
        delta = np.diff(prices, axis=0)  # (T-1, N)
        gain = np.where(delta > 0, delta, 0.0)
        loss = np.where(delta < 0, -delta, 0.0)

        # Wilder 平滑（EMA with alpha=1/period）
        alpha = 1.0 / period
        avg_gain = np.zeros((T, N))
        avg_loss = np.zeros((T, N))

        # 初始窗口用简单均值
        if T - 1 >= period:
            avg_gain[period] = np.mean(gain[:period], axis=0)
            avg_loss[period] = np.mean(loss[:period], axis=0)

            for t in range(period + 1, T):
                avg_gain[t] = alpha * gain[t - 1] + (1 - alpha) * avg_gain[t - 1]
                avg_loss[t] = alpha * loss[t - 1] + (1 - alpha) * avg_loss[t - 1]

        rs = avg_gain / (avg_loss + 1e-9)
        rsi = 100.0 - 100.0 / (1.0 + rs)

        for t in range(period + 1, T):
            valid = ~np.isnan(rsi[t])
            buy = valid & (rsi[t] < oversold) & (rsi[t - 1] >= oversold)
            sell = valid & (rsi[t] > overbought) & (rsi[t - 1] <= overbought)
            signals[t][buy] = 1
            signals[t][sell] = -1
        return signals
