"""
策略注册表
==========
自动发现 strategies/ 下的所有策略，按 id 索引。
提供 get_strategy / list_strategies API。
"""

from services.strategies.base import BaseStrategy
from services.strategies.macd import MacdStrategy
from services.strategies.bband import BbandStrategy
from services.strategies.timing import TimingStrategy
from services.strategies.turtle import TurtleStrategy
from services.strategies.multifactor import MultifactorStrategy
from services.strategies.double_low_cb import DoubleLowCbStrategy
from services.strategies.volume_breakout import VolumeBreakoutStrategy
from services.strategies.grid import GridStrategy
from services.strategies.etf_momentum import EtfMomentumStrategy
from services.strategies.event_driven import EventDrivenStrategy

# 注册表
_REGISTRY: dict[str, BaseStrategy] = {}


def _register(cls):
    inst = cls()
    _REGISTRY[inst.id] = inst


_register(MacdStrategy)
_register(BbandStrategy)
_register(TimingStrategy)
_register(TurtleStrategy)
_register(MultifactorStrategy)
_register(DoubleLowCbStrategy)
_register(VolumeBreakoutStrategy)
_register(GridStrategy)
_register(EtfMomentumStrategy)
_register(EventDrivenStrategy)


def get_strategy(strategy_id: str) -> BaseStrategy | None:
    """按 id 获取策略实例"""
    return _REGISTRY.get(strategy_id)


def list_strategies() -> list[dict]:
    """返回所有策略的 JSON 描述（含参数 Schema）"""
    return [s.to_dict() for s in _REGISTRY.values()]


def get_strategy_params(strategy_id: str) -> list[dict] | None:
    """获取指定策略的参数 Schema"""
    s = _REGISTRY.get(strategy_id)
    return s.to_dict()["params"] if s else None
