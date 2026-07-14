"""
面板数据加载器
==============
将 SQLite 中的日线数据转为面板结构：{field: DataFrame(index=date, columns=code)}。
整个因子研究框架的数据基础。

用法:
    panel = load_panel(['000001.SZ', '600519.SH'], '2025-01-01', '2025-12-31')
    panel['close']  →  DataFrame(252 rows × 2 cols)
"""

import structlog
import numpy as np
import pandas as pd
from typing import List, Optional
from hashlib import md5

log = structlog.get_logger(__name__)

# 可用的面板字段及其来源
OHLCV_FIELDS = ['open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']
FACTOR_FIELDS = ['pe_ttm', 'pb', 'ps_ttm', 'turnover_rate', 'total_mv', 'dv_ttm', 'circ_mv']
ALL_FIELDS = OHLCV_FIELDS + FACTOR_FIELDS

# 面板缓存（避免重复查询，key = hash(codes + dates + fields)）
_panel_cache: dict = {}
_MAX_CACHE = 5


def _cache_key(codes: list, start_date: str, end_date: str, fields: list) -> str:
    raw = f"{sorted(codes)}|{start_date}|{end_date}|{sorted(fields)}"
    return md5(raw.encode()).hexdigest()


def load_panel(
    codes: List[str],
    start_date: str,
    end_date: str,
    fields: Optional[List[str]] = None,
) -> dict[str, pd.DataFrame]:
    """
    加载面板数据。

    Args:
        codes: 股票代码列表
        start_date / end_date: 日期范围 (YYYY-MM-DD)
        fields: 需要的字段列表，默认 OHLCV + pct_chg

    Returns:
        {field_name: DataFrame(index=DatetimeIndex, columns=codes)}
        每个 DataFrame 的 index 是交易日，columns 是股票代码。
    """
    if not codes:
        return {}

    if fields is None:
        fields = OHLCV_FIELDS

    # 分离行情字段和估值字段
    bar_fields = [f for f in fields if f in OHLCV_FIELDS]
    factor_fields = [f for f in fields if f in FACTOR_FIELDS]

    # 查缓存
    ck = _cache_key(codes, start_date, end_date, fields)
    if ck in _panel_cache:
        return _panel_cache[ck]

    panel = {}

    # 加载行情数据
    if bar_fields:
        panel.update(_load_bar_panel(codes, start_date, end_date, bar_fields))

    # 加载估值因子数据
    if factor_fields:
        panel.update(_load_factor_panel(codes, start_date, end_date, factor_fields))

    # 写缓存
    if len(_panel_cache) >= _MAX_CACHE:
        oldest = next(iter(_panel_cache))
        del _panel_cache[oldest]
    _panel_cache[ck] = panel

    field_shapes = {k: v.shape for k, v in panel.items()}
    log.info("panel_loaded", codes=len(codes), fields=list(panel.keys()),
             shapes=field_shapes, date_range=f"{start_date}~{end_date}")
    return panel


def _load_bar_panel(
    codes: list, start_date: str, end_date: str, fields: list
) -> dict[str, pd.DataFrame]:
    """从 StockDailyBar 加载行情面板"""
    from core.database import db_session
    from models.quant_data import StockDailyBar

    columns_to_query = [StockDailyBar.code, StockDailyBar.trade_date]
    for f in fields:
        col = getattr(StockDailyBar, f, None)
        if col is not None:
            columns_to_query.append(col)

    with db_session() as db:
        rows = (
            db.query(*columns_to_query)
            .filter(
                StockDailyBar.code.in_(codes),
                StockDailyBar.trade_date >= start_date,
                StockDailyBar.trade_date <= end_date,
            )
            .all()
        )

    if not rows:
        return {}

    col_names = ['code', 'trade_date'] + [f for f in fields if hasattr(StockDailyBar, f)]
    df = pd.DataFrame(rows, columns=col_names)
    df['trade_date'] = pd.to_datetime(df['trade_date'])

    panel = {}
    for field in fields:
        if field not in df.columns:
            continue
        pivot = df.pivot_table(index='trade_date', columns='code', values=field, aggfunc='last')
        pivot = pivot.sort_index()
        # 确保所有 codes 都在列中（缺失的填 NaN）
        for c in codes:
            if c not in pivot.columns:
                pivot[c] = np.nan
        pivot = pivot[codes]  # 按输入顺序排列
        panel[field] = pivot.astype(float)

    return panel


def _load_factor_panel(
    codes: list, start_date: str, end_date: str, fields: list
) -> dict[str, pd.DataFrame]:
    """从 StockDailyFactor 加载估值因子面板"""
    from core.database import db_session
    from models.quant_data import StockDailyFactor

    columns_to_query = [StockDailyFactor.code, StockDailyFactor.trade_date]
    for f in fields:
        col = getattr(StockDailyFactor, f, None)
        if col is not None:
            columns_to_query.append(col)

    with db_session() as db:
        rows = (
            db.query(*columns_to_query)
            .filter(
                StockDailyFactor.code.in_(codes),
                StockDailyFactor.trade_date >= start_date,
                StockDailyFactor.trade_date <= end_date,
            )
            .all()
        )

    if not rows:
        return {}

    col_names = ['code', 'trade_date'] + [f for f in fields if hasattr(StockDailyFactor, f)]
    df = pd.DataFrame(rows, columns=col_names)
    df['trade_date'] = pd.to_datetime(df['trade_date'])

    panel = {}
    for field in fields:
        if field not in df.columns:
            continue
        pivot = df.pivot_table(index='trade_date', columns='code', values=field, aggfunc='last')
        pivot = pivot.sort_index()
        for c in codes:
            if c not in pivot.columns:
                pivot[c] = np.nan
        pivot = pivot[codes]
        panel[field] = pivot.astype(float)

    return panel


def load_industry_map(codes: List[str]) -> dict[str, str]:
    """加载股票→行业映射 {code: industry_name}"""
    from core.database import db_session
    from models.quant_data import StockBasicInfo

    with db_session() as db:
        rows = (
            db.query(StockBasicInfo.code, StockBasicInfo.industry)
            .filter(StockBasicInfo.code.in_(codes))
            .all()
        )
    return {r.code: (r.industry or "其他") for r in rows}


def get_trade_dates(start_date: str, end_date: str) -> list[str]:
    """获取区间内的交易日列表"""
    from core.database import db_session
    from models.quant_data import StockDailyBar

    with db_session() as db:
        dates = [
            str(r[0]) for r in
            db.query(StockDailyBar.trade_date)
            .filter(
                StockDailyBar.trade_date >= start_date,
                StockDailyBar.trade_date <= end_date,
            )
            .distinct()
            .order_by(StockDailyBar.trade_date)
            .all()
        ]
    return dates


def get_rebalance_dates(
    trade_dates: list[str], freq: str = 'monthly'
) -> list[str]:
    """从交易日列表中提取调仓日期（月末/周末/季末）"""
    if not trade_dates:
        return []

    dates = pd.to_datetime(trade_dates)

    if freq == 'weekly':
        # 每周最后一个交易日
        groups = dates.to_series().groupby(dates.isocalendar().week)
        return [str(g.iloc[-1].date()) for _, g in groups]
    elif freq == 'quarterly':
        groups = dates.to_series().groupby(dates.to_period('Q'))
        return [str(g.iloc[-1].date()) for _, g in groups]
    else:  # monthly
        groups = dates.to_series().groupby(dates.to_period('M'))
        return [str(g.iloc[-1].date()) for _, g in groups]


def clear_cache():
    """清空面板缓存"""
    _panel_cache.clear()
