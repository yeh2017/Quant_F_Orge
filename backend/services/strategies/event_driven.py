"""事件驱动择时策略 — 基于新闻事件信号买入，持仓 N 天后卖出"""

import numpy as np
from services.strategies.base import BaseStrategy, StrategyParam


class EventDrivenStrategy(BaseStrategy):
    id = "event_driven"
    name = "事件驱动"
    desc = "基于新闻事件信号的择时策略"
    detail = "业绩/重组/大宗/解禁/龙虎榜等事件触发买入 | 持仓N天后卖出 | 可配事件类型和持仓周期"
    is_signal_based = True
    needs_event = True  # 告诉引擎需要注入事件矩阵

    def params_schema(self):
        return [
            StrategyParam("event_type", "事件类型", "select", "业绩",
                          options=[{"value": et, "label": et}
                                   for et in ["业绩", "资金", "分红", "重组", "诉讼", "人事",
                                              "大宗交易", "解禁", "龙虎榜"]]),
            StrategyParam("direction", "事件方向", "select", "positive",
                          options=[
                              {"value": "positive", "label": "利好事件"},
                              {"value": "negative", "label": "利空事件"},
                              {"value": "both", "label": "不限"},
                          ]),
            StrategyParam("hold_days", "持仓天数", "int", 5, min=1, max=20, step=1),
            StrategyParam("min_score", "最低情绪分", "float", 0.3, min=0.1, max=0.9, step=0.1),
        ]

    def generate_signals(self, prices, params, volume=None):
        """
        从 params["_event_matrix"] 读取 (T, N) 事件矩阵，
        event_matrix[t][j] = sentiment_score（有事件时）或 0（无事件时）。
        根据 direction 过滤后，生成买入信号并在 hold_days 后卖出。
        """
        event_matrix = params.get("_event_matrix")
        hold_days = params.get("hold_days", 5)
        min_score = params.get("min_score", 0.3)
        direction = params.get("direction", "positive")

        T, N = prices.shape
        signals = np.zeros((T, N))
        if event_matrix is None:
            return signals

        for j in range(N):
            remaining = 0
            for t in range(T):
                score = event_matrix[t, j]
                # 根据方向过滤事件
                triggered = False
                if direction == "positive" and score >= min_score:
                    triggered = True
                elif direction == "negative" and score <= -min_score:
                    triggered = True
                elif direction == "both" and abs(score) >= min_score:
                    triggered = True

                if triggered:
                    signals[t, j] = 1  # 买入
                    remaining = hold_days
                elif remaining > 0:
                    remaining -= 1
                    if remaining == 0:
                        signals[t, j] = -1  # 持仓到期卖出
        return signals
