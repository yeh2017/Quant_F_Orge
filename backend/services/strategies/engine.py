"""
回测模拟引擎
=============
纯矩阵运算：权重变化序列 + 价格矩阵 → 净值曲线 + 绩效指标。
所有策略共享同一引擎，不含任何策略逻辑。
"""

import numpy as np
import structlog
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from settings import RF_ANNUAL, TRADING_DAYS

log = structlog.get_logger(__name__)


@dataclass
class BacktestResult:
    """回测结果数据类"""
    start_value: float = 0
    end_value: float = 0
    total_return: float = 0
    annual_return: float = 0
    benchmark_return: float = 0
    excess_return: float = 0
    sharpe_ratio: float = 0
    sortino_ratio: float = 0
    max_drawdown: float = 0
    calmar_ratio: float = 0
    volatility: float = 0
    win_rate: float = 0
    total_trades: int = 0
    avg_holding_days: int = 0
    cum_returns: list = field(default_factory=list)
    benchmark: list = field(default_factory=list)
    drawdowns: list = field(default_factory=list)
    trade_markers: dict = field(default_factory=dict)
    monthly_returns: list = field(default_factory=list)
    dates: list = field(default_factory=list)
    holdings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "start_value": self.start_value,
            "end_value": self.end_value,
            "total_return": self.total_return,
            "annual_return": self.annual_return,
            "benchmark_return": self.benchmark_return,
            "excess_return": self.excess_return,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "max_drawdown": self.max_drawdown,
            "calmar_ratio": self.calmar_ratio,
            "volatility": self.volatility,
            "win_rate": self.win_rate,
            "total_trades": self.total_trades,
            "avg_holding_days": self.avg_holding_days,
            "cumReturns": self.cum_returns,
            "benchmark": self.benchmark,
            "drawdowns": self.drawdowns,
            "trade_markers": self.trade_markers,
            "monthly_returns": self.monthly_returns,
            "dates": self.dates,
            "holdings": self.holdings,
        }


class BacktestEngine:
    """回测模拟引擎（纯矩阵运算）"""

    RF_DAILY = RF_ANNUAL / TRADING_DAYS

    def calc_performance(
        self,
        portfolio_rets: np.ndarray,
        initial_cash: float,
        rebal_indices: List[int],
        T: int,
        bench_daily: Optional[List[float]],
        trade_markers: Dict[str, list],
        dates: Optional[List[str]] = None,
    ) -> BacktestResult:
        """
        根据组合日收益序列计算全部绩效指标。

        Args:
            portfolio_rets: (T-1,) 每日组合收益率
            initial_cash: 初始资金
            rebal_indices: 再平衡日下标
            T: 总交易日数
            bench_daily: 基准日收益率
            trade_markers: 交易标记
        """
        cum_returns = np.cumprod(1 + portfolio_rets).tolist()
        nv = np.array(cum_returns)

        total_return = round(float(nv[-1] - 1) * 100, 2)
        n_years = (T - 1) / TRADING_DAYS
        annual_return = round(float(nv[-1] ** (1 / max(n_years, 0.01)) - 1) * 100, 2)

        # 波动率
        vol = round(float(np.std(portfolio_rets) * np.sqrt(TRADING_DAYS) * 100), 2)

        # 夏普（波动率过小时返回 0，与 risk_service 一致）
        excess = portfolio_rets - self.RF_DAILY
        excess_std = float(np.std(excess))
        sharpe = round(float(np.mean(excess) / excess_std * np.sqrt(TRADING_DAYS)), 2) if excess_std > 1e-6 else 0.0

        # 最大回撤
        peak = np.maximum.accumulate(nv)
        dd_arr = (nv - peak) / peak * 100
        max_dd = round(float(-np.min(dd_arr)), 2)

        # Sortino（下行波动率过小时返回 0）
        down = portfolio_rets[portfolio_rets < 0]
        down_std = float(np.std(down) * np.sqrt(TRADING_DAYS) * 100) if len(down) > 1 else vol
        sortino = round(annual_return / down_std, 2) if down_std > 0.01 else 0.0

        # Calmar
        calmar = round(annual_return / max(max_dd, 1e-4), 2)

        # 基准
        bench_cum = np.cumprod(1 + np.array(bench_daily)).tolist() if bench_daily else []
        bench_return = round(float((bench_cum[-1] - 1) * 100), 2) if bench_cum else 0.0

        # 胜率（按再平衡周期）
        period_rets = []
        for j in range(len(rebal_indices)):
            start_i = rebal_indices[j]
            end_i = rebal_indices[j + 1] if j + 1 < len(rebal_indices) else T - 1
            if start_i < len(portfolio_rets) and end_i <= len(portfolio_rets):
                period_cum = float(np.prod(1 + portfolio_rets[start_i:end_i]) - 1)
                period_rets.append(period_cum)
        win_rate = round(sum(r > 0 for r in period_rets) / max(len(period_rets), 1) * 100, 1)

        return BacktestResult(
            start_value=initial_cash,
            end_value=round(initial_cash * nv[-1], 2),
            total_return=total_return,
            annual_return=annual_return,
            benchmark_return=bench_return,
            excess_return=round(total_return - bench_return, 2),
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown=max_dd,
            calmar_ratio=calmar,
            volatility=vol,
            win_rate=win_rate,
            total_trades=len(rebal_indices),
            avg_holding_days=round((T - 1) / max(len(rebal_indices), 1)),
            cum_returns=cum_returns,
            benchmark=bench_cum,
            drawdowns=dd_arr.tolist(),
            trade_markers=trade_markers,
            monthly_returns=self._calc_monthly_returns(portfolio_rets, dates),
        )

    @staticmethod
    def _calc_monthly_returns(
        portfolio_rets: np.ndarray, dates: Optional[List[str]]
    ) -> list:
        """按月聚合收益率，返回 [{month, return}, ...]"""
        if dates is None or len(dates) < 2:
            return []
        # dates 比 portfolio_rets 多 1 个元素（dates[0] 对应初始日）
        ret_dates = dates[1:] if len(dates) > len(portfolio_rets) else dates
        monthly = {}
        for d, r in zip(ret_dates, portfolio_rets):
            m = d[:7]  # "2025-01"
            if m not in monthly:
                monthly[m] = 1.0
            monthly[m] *= (1 + r)
        return [
            {"month": m, "return": round(float((v - 1) * 100), 2)}
            for m, v in sorted(monthly.items())
        ]
