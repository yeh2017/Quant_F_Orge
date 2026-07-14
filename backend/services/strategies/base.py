"""
策略基类与参数 Schema
=====================
所有策略继承 BaseStrategy，定义参数 Schema 供前端动态渲染。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, List, Optional
import numpy as np


@dataclass
class StrategyParam:
    """策略参数描述（前端用来渲染输入控件）"""
    name: str             # 参数键名（传后端用）
    label: str            # 中文标签（前端显示）
    type: str             # int / float / select
    default: Any          # 默认值
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    options: Optional[list] = None  # select: [{value, label}]


class BaseStrategy(ABC):
    """策略基类 — 每个策略只需实现 generate_signals + params_schema"""

    id: str = ""
    name: str = ""
    desc: str = ""
    detail: str = ""
    # 是否需要因子评分（multifactor / convertible 需要）
    needs_factor: bool = False
    # 是否为信号驱动（逐日更新权重 vs 再平衡日调仓）
    is_signal_based: bool = True
    # 是否允许对已持仓标的重复发信号（网格等加减仓策略需要）
    allow_reentry: bool = False

    @abstractmethod
    def params_schema(self) -> List[StrategyParam]:
        """返回该策略的可配参数列表"""

    @abstractmethod
    def generate_signals(self, prices: np.ndarray, params: dict, volume: np.ndarray = None) -> np.ndarray:
        """
        输入 (T, N) 收盘价矩阵，输出 (T, N) 信号矩阵。
        +1=买入  -1=卖出  0=持有不变
        volume: 可选 (T, N) 成交量矩阵，供量价策略使用
        """

    def to_dict(self) -> dict:
        """序列化为前端可用的 JSON"""
        return {
            "id": self.id,
            "name": self.name,
            "desc": self.desc,
            "detail": self.detail,
            "params": [
                {k: v for k, v in {
                    "name": p.name, "label": p.label, "type": p.type,
                    "default": p.default, "min": p.min, "max": p.max,
                    "step": p.step, "options": p.options,
                }.items() if v is not None}
                for p in self.params_schema()
            ],
        }


# ── 公用工具函数（实现已移至 utils/indicators.py，此处 re-export 保持向后兼容）──

from utils.indicators import sma, ema  # noqa: F401

