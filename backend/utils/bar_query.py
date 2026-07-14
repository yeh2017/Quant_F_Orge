"""
日线行情统一查询辅助模块
根据 code 自动路由到 StockDailyBar 或 EtfDailyBar
"""
from functools import lru_cache
from models.quant_data import StockDailyBar, EtfDailyBar, EtfBasicInfo, ConvertibleBondBar
from core.database import db_session
from utils.asset_type import is_bond as _is_bond_by_prefix


@lru_cache(maxsize=1)
def _etf_code_set() -> frozenset:
    """缓存 ETF 代码集合（同时包含带后缀和6位两种格式）"""
    with db_session() as db:
        codes = [r[0] for r in db.query(EtfBasicInfo.code).all()]
    full = set(codes)
    short = {c.split('.')[0] for c in codes if '.' in c}
    return frozenset(full | short)


@lru_cache(maxsize=1)
def _etf_short_to_full() -> dict:
    """6位代码 → DB 格式的映射表（如 159100 → 159100.SZ）"""
    with db_session() as db:
        codes = [r[0] for r in db.query(EtfBasicInfo.code).all()]
    return {c.split('.')[0]: c for c in codes if '.' in c}


def refresh_etf_cache():
    """手动刷新 ETF 缓存（同步完 ETF 列表后调用）"""
    _etf_code_set.cache_clear()
    _etf_short_to_full.cache_clear()


def to_db_code(code: str) -> str:
    """将任意格式代码转为 DB 格式（带交易所后缀）
    ETF: 查映射表（准确）
    可转债: 原样返回（DB 存纯 6 位码）
    股票: 按首位推断后缀（6→.SH, 其余→.SZ）
    已带后缀则原样返回
    """
    if '.' in code:
        return code
    # 可转债在 DB 中存纯 6 位码，不加后缀
    if is_bond(code):
        return code
    # ETF 优先查表
    mapping = _etf_short_to_full()
    if code in mapping:
        return mapping[code]
    # 股票按规则推断
    from utils.asset_type import to_ts_code
    return to_ts_code(code)


def is_etf(code: str) -> bool:
    return code in _etf_code_set()


def is_bond(code: str) -> bool:
    """判断是否为可转债代码（委托 asset_type 统一判断）"""
    return _is_bond_by_prefix(code)


def get_bar_model(code: str):
    """根据 code 返回对应的 ORM 模型（股票/ETF/可转债）"""
    if is_bond(code):
        return ConvertibleBondBar
    return EtfDailyBar if is_etf(code) else StockDailyBar


def classify_codes(codes: list) -> tuple:
    """
    将混合代码列表分为 (stock_codes, etf_codes, bond_codes)
    返回的代码均为 DB 格式，确保 SQL 查询能匹配
    """
    etf_set = _etf_code_set()
    stock_codes = [to_db_code(c) for c in codes if not is_bond(c) and c not in etf_set]
    etf_codes = [to_db_code(c) for c in codes if c in etf_set]
    bond_codes = [to_db_code(c) for c in codes if is_bond(c)]
    return stock_codes, etf_codes, bond_codes


def query_bars(db, codes: list, filters: list = None):
    """
    统一批量查询日线（自动合并两张表的结果）
    返回 list of (code, trade_date, close, ...) rows
    """
    stock_codes, etf_codes, bond_codes = classify_codes(codes)
    results = []

    for model, sub_codes in [
        (StockDailyBar, stock_codes),
        (EtfDailyBar, etf_codes),
        (ConvertibleBondBar, bond_codes),
    ]:
        if not sub_codes:
            continue
        q = db.query(model.code, model.trade_date, model.close).filter(
            model.code.in_(sub_codes)
        )
        if filters:
            for f in filters:
                q = q.filter(f(model))
        results.extend(q.all())

    return results

