"""
分层回测
========
将股票按因子值分为 N 组，计算各组前瞻收益，验证因子有效性。

核心度量：
- 各组累计收益（单调递减 = 因子有效）
- 多空收益（Top 组 - Bottom 组）
- IC 序列（Rank IC + ICIR）
- 单调性评分

用法:
    result = stratified_backtest(factor_panel, return_panel, n_groups=5)
"""

import numpy as np
import pandas as pd
import structlog
from scipy import stats as sp_stats

log = structlog.get_logger(__name__)


def stratified_backtest(
    factor_panel: pd.DataFrame,
    return_panel: pd.DataFrame,
    n_groups: int = 5,
    rebalance_dates: list[str] | None = None,
) -> dict:
    """
    分层回测：按因子值分组，检验各组收益差异。

    Args:
        factor_panel: 因子值面板 (date × code)
        return_panel: 收益率面板 (date × code)，通常为 pct_chg / 100
        n_groups: 分组数（默认 5 分位）
        rebalance_dates: 调仓日期列表；None 则用全部日期

    Returns:
        {
            "groups": [{id, label, annual_return, cum_returns, dates}],
            "long_short": {annual_return, sharpe, max_drawdown, cum_returns},
            "ic_series": {dates, values, ic_mean, ic_std, ic_ir},
            "monotonicity_score": float,
            "summary": str,
        }
    """
    # 对齐两个面板的日期和股票
    common_dates = factor_panel.index.intersection(return_panel.index)
    common_codes = factor_panel.columns.intersection(return_panel.columns)

    if len(common_dates) < 10 or len(common_codes) < 20:
        return {"error": f"数据不足：{len(common_dates)} 天 × {len(common_codes)} 只股票"}

    factor = factor_panel.loc[common_dates, common_codes].copy()
    returns = return_panel.loc[common_dates, common_codes].copy()

    # 确定调仓日期
    if rebalance_dates:
        rb_dates = pd.DatetimeIndex([d for d in rebalance_dates if d in factor.index])
    else:
        rb_dates = factor.index

    if len(rb_dates) < 5:
        return {"error": f"调仓期数不足: {len(rb_dates)}"}

    # ── 逐期分组（相邻调仓日之间的持仓收益） ──
    group_returns = {g: [] for g in range(1, n_groups + 1)}
    ic_values = []
    valid_dates = []

    for i in range(len(rb_dates) - 1):
        date_start = rb_dates[i]
        date_end = rb_dates[i + 1]

        # 在调仓日取因子值
        f_row = factor.loc[date_start].dropna()
        if len(f_row) < n_groups * 3:
            continue

        # 计算 date_start → date_end 期间的累计收益（前瞻收益）
        period_mask = (returns.index > date_start) & (returns.index <= date_end)
        if period_mask.sum() == 0:
            continue
        # 每只股票在持仓期间的累计收益: prod(1 + daily_ret) - 1
        period_ret = (1 + returns.loc[period_mask]).prod() - 1

        # 取因子和期间收益的交集
        common = f_row.index.intersection(period_ret.dropna().index)
        if len(common) < n_groups * 3:
            continue

        f_vals = f_row[common]
        r_vals = period_ret[common]

        # 计算 Rank IC（因子值 vs 前瞻期间收益）
        ic, _ = sp_stats.spearmanr(f_vals.values, r_vals.values)
        if np.isfinite(ic):
            ic_values.append(float(ic))
        else:
            ic_values.append(0.0)
        valid_dates.append(str(date_start.date()) if hasattr(date_start, 'date') else str(date_start))

        # 按因子值分位分组
        labels = _assign_groups(f_vals, n_groups)
        for g in range(1, n_groups + 1):
            mask = labels == g
            if mask.sum() > 0:
                group_ret = float(r_vals[mask].mean())
            else:
                group_ret = 0.0
            group_returns[g].append(group_ret)

    if len(valid_dates) < 5:
        return {"error": f"有效截面不足: {len(valid_dates)}"}

    # ── 组装结果 ──
    groups = []
    for g in range(1, n_groups + 1):
        rets = np.array(group_returns[g])
        cum = _cum_returns(rets)
        annual_ret = _annualize_return(rets)
        pct_label = _group_label(g, n_groups)
        groups.append({
            "id": g,
            "label": pct_label,
            "annual_return": round(annual_ret, 4),
            "cum_returns": [round(v, 4) for v in cum],
        })

    # 多空收益（Top 组 - Bottom 组）
    ls_rets = np.array(group_returns[1]) - np.array(group_returns[n_groups])
    ls_cum = _cum_returns(ls_rets)
    ls_annual = _annualize_return(ls_rets)
    ls_sharpe = _sharpe_ratio(ls_rets)
    ls_mdd = _max_drawdown(ls_cum)

    long_short = {
        "annual_return": round(ls_annual, 4),
        "sharpe": round(ls_sharpe, 4),
        "max_drawdown": round(ls_mdd, 4),
        "cum_returns": [round(v, 4) for v in ls_cum],
    }

    # IC 序列
    ic_arr = np.array(ic_values)
    ic_mean = float(np.mean(ic_arr))
    ic_std = float(np.std(ic_arr)) if len(ic_arr) > 1 else 0.0
    ic_ir = ic_mean / ic_std if ic_std > 1e-6 else 0.0

    ic_series = {
        "dates": valid_dates,
        "values": [round(v, 4) for v in ic_values],
        "ic_mean": round(ic_mean, 4),
        "ic_std": round(ic_std, 4),
        "ic_ir": round(ic_ir, 4),
    }

    # 单调性评分
    group_annuals = [g["annual_return"] for g in groups]
    mono = _monotonicity_score(group_annuals)

    # 综合判定
    summary = _make_summary(ic_mean, ic_ir, mono, ls_annual)

    result = {
        "groups": groups,
        "long_short": long_short,
        "ic_series": ic_series,
        "monotonicity_score": round(mono, 2),
        "dates": valid_dates,
        "stock_count": len(common_codes),
        "period_count": len(valid_dates),
        "summary": summary,
    }

    log.info("stratified_backtest_done",
             periods=len(valid_dates), stocks=len(common_codes),
             ic_mean=round(ic_mean, 4), mono=round(mono, 2))
    return result


# ── 辅助函数 ──

def _assign_groups(factor_series: pd.Series, n_groups: int) -> pd.Series:
    """按因子值分位分组，1 = Top（因子值最大），n = Bottom"""
    ranks = factor_series.rank(pct=True)
    labels = pd.cut(ranks, bins=n_groups, labels=False, include_lowest=True) + 1
    # 反转：rank 最高的（因子值最大）放 Group 1
    labels = n_groups + 1 - labels
    return labels


def _cum_returns(period_returns: np.ndarray) -> list[float]:
    """计算累计净值曲线（从 1.0 开始）"""
    cum = np.cumprod(1 + period_returns)
    return [1.0] + cum.tolist()


def _annualize_return(period_returns: np.ndarray, periods_per_year: int = 12) -> float:
    """年化收益率（假设月度调仓）"""
    n = len(period_returns)
    if n == 0:
        return 0.0
    total = np.prod(1 + period_returns)
    if total <= 0:
        return -1.0
    return float(total ** (periods_per_year / n) - 1)


def _sharpe_ratio(period_returns: np.ndarray, rf: float = 0.03, periods_per_year: int = 12) -> float:
    """夏普比率"""
    if len(period_returns) < 2:
        return 0.0
    excess = period_returns - rf / periods_per_year
    mean_ret = np.mean(excess)
    std_ret = np.std(excess, ddof=1)
    if std_ret < 1e-8:
        return 0.0
    return float(mean_ret / std_ret * np.sqrt(periods_per_year))


def _max_drawdown(cum_returns: list[float]) -> float:
    """最大回撤"""
    peak = cum_returns[0]
    mdd = 0.0
    for v in cum_returns:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0
        if dd > mdd:
            mdd = dd
    return mdd


def _group_label(g: int, n: int) -> str:
    """生成组标签"""
    pct = 100 // n
    start = (g - 1) * pct
    end = g * pct
    if g == 1:
        return f"Top {pct}%"
    elif g == n:
        return f"Bottom {pct}%"
    return f"{start}-{end}%"


def _monotonicity_score(group_returns: list[float]) -> float:
    """
    单调性评分：各组收益是否单调递减。
    1.0 = 完全单调递减（完美因子）
    0.0 = 无序
    """
    n = len(group_returns)
    if n < 2:
        return 0.0

    concordant = 0
    total = 0
    for i in range(n):
        for j in range(i + 1, n):
            total += 1
            # Group i 排名更靠前，应该收益更高
            if group_returns[i] > group_returns[j]:
                concordant += 1

    return concordant / total if total > 0 else 0.0


def _make_summary(ic_mean: float, ic_ir: float, mono: float, ls_annual: float) -> str:
    """生成一句话总结"""
    parts = []

    # IC 判定
    abs_ic = abs(ic_mean)
    if abs_ic >= 0.05 and abs(ic_ir) >= 0.5:
        parts.append(f"IC均值={ic_mean:.3f}, ICIR={ic_ir:.2f} ✅ 强有效")
    elif abs_ic >= 0.03 and abs(ic_ir) >= 0.3:
        parts.append(f"IC均值={ic_mean:.3f}, ICIR={ic_ir:.2f} ✅ 有效")
    elif abs_ic >= 0.02:
        parts.append(f"IC均值={ic_mean:.3f} ➖ 弱相关")
    else:
        parts.append(f"IC均值={ic_mean:.3f} ❌ 无效")

    # 单调性
    if mono >= 0.8:
        parts.append(f"单调性={mono:.0%} ✅")
    elif mono >= 0.6:
        parts.append(f"单调性={mono:.0%} ➖")
    else:
        parts.append(f"单调性={mono:.0%} ❌")

    # 多空收益
    if ls_annual > 0.1:
        parts.append(f"多空年化={ls_annual:.1%} ✅")
    elif ls_annual > 0:
        parts.append(f"多空年化={ls_annual:.1%} ➖")
    else:
        parts.append(f"多空年化={ls_annual:.1%} ❌")

    return " | ".join(parts)
