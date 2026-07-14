"""
交易日期工具 — 唯一权威来源
==============================
所有模块通过本模块判断交易日、获取最近交易日、校正同步日期。
避免 datetime.now() / weekday() 散落导致节假日误判。
"""

from datetime import date, timedelta
from typing import Optional
import structlog

log = structlog.get_logger("trade_date")

# ── 中国A股法定节假日（国务院公布，按年维护）──
# 只列"自然日里需要休市但不是周末"的日期
# 补班日（周六开市）不需要列——Tushare trade_cal 会正确标记
CN_HOLIDAYS = {
    # 2020
    '2020-01-01', '2020-01-24', '2020-01-25', '2020-01-26', '2020-01-27',
    '2020-01-28', '2020-01-29', '2020-01-30',
    '2020-04-06', '2020-05-01', '2020-05-04', '2020-05-05',
    '2020-06-25', '2020-06-26',
    '2020-10-01', '2020-10-02', '2020-10-05', '2020-10-06', '2020-10-07', '2020-10-08',
    # 2021
    '2021-01-01', '2021-02-11', '2021-02-12', '2021-02-15', '2021-02-16', '2021-02-17',
    '2021-04-05', '2021-05-03', '2021-05-04', '2021-05-05',
    '2021-06-14', '2021-09-20', '2021-09-21',
    '2021-10-01', '2021-10-04', '2021-10-05', '2021-10-06', '2021-10-07',
    # 2022
    '2022-01-03', '2022-01-31', '2022-02-01', '2022-02-02', '2022-02-03', '2022-02-04',
    '2022-04-04', '2022-04-05', '2022-05-02', '2022-05-03', '2022-05-04',
    '2022-06-03', '2022-09-12',
    '2022-10-03', '2022-10-04', '2022-10-05', '2022-10-06', '2022-10-07',
    # 2023
    '2023-01-02', '2023-01-23', '2023-01-24', '2023-01-25', '2023-01-26', '2023-01-27',
    '2023-04-05', '2023-04-29', '2023-05-01', '2023-05-02', '2023-05-03',
    '2023-06-22', '2023-06-23',
    '2023-09-29',
    '2023-10-02', '2023-10-03', '2023-10-04', '2023-10-05', '2023-10-06',
    # 2024
    '2024-01-01', '2024-02-09', '2024-02-12', '2024-02-13', '2024-02-14',
    '2024-02-15', '2024-02-16',
    '2024-04-04', '2024-04-05',
    '2024-05-01', '2024-05-02', '2024-05-03',
    '2024-06-10',
    '2024-09-16', '2024-09-17',
    '2024-10-01', '2024-10-02', '2024-10-03', '2024-10-04', '2024-10-07',
    # 2025
    '2025-01-01', '2025-01-28', '2025-01-29', '2025-01-30', '2025-01-31',
    '2025-02-03', '2025-02-04',
    '2025-04-04', '2025-05-01', '2025-05-02', '2025-05-05',
    '2025-05-31', '2025-06-02',
    '2025-10-01', '2025-10-02', '2025-10-03', '2025-10-06', '2025-10-07', '2025-10-08',
    # 2026
    '2026-01-01', '2026-01-02',
    '2026-02-17', '2026-02-18', '2026-02-19', '2026-02-20', '2026-02-23',
    '2026-04-06', '2026-05-01', '2026-05-04', '2026-05-05',
    '2026-06-19',
    '2026-09-25',
    '2026-10-01', '2026-10-02', '2026-10-05', '2026-10-06', '2026-10-07',
    # 2027（预估，国务院通常12月底公布）
    '2027-01-01', '2027-02-08', '2027-02-09', '2027-02-10', '2027-02-11', '2027-02-12',
    '2027-04-05', '2027-05-03', '2027-05-04',
    '2027-06-09',
    '2027-10-01', '2027-10-04', '2027-10-05', '2027-10-06', '2027-10-07',
    # 2028（预估）
    '2028-01-03', '2028-01-26', '2028-01-27', '2028-01-28', '2028-01-31',
    '2028-04-04', '2028-05-01', '2028-05-02', '2028-05-03',
    '2028-06-05',
    '2028-10-02', '2028-10-03', '2028-10-04', '2028-10-05', '2028-10-06',
    # 2029（预估）
    '2029-01-01', '2029-02-13', '2029-02-14', '2029-02-15', '2029-02-16', '2029-02-19',
    '2029-04-05', '2029-04-06', '2029-05-01', '2029-05-02',
    '2029-06-18',
    '2029-10-01', '2029-10-02', '2029-10-03', '2029-10-04', '2029-10-05',
    # 2030（预估）
    '2030-01-01', '2030-02-04', '2030-02-05', '2030-02-06', '2030-02-07', '2030-02-08',
    '2030-04-05', '2030-05-01', '2030-05-02', '2030-05-03',
    '2030-06-07',
    '2030-10-01', '2030-10-02', '2030-10-03', '2030-10-04', '2030-10-07',
}

# ── Tushare 交易日历缓存（进程级，首次加载后不再请求）──
_trade_dates_cache: Optional[set] = None   # {'2020-01-02', ...} 所有交易日
_cache_source: Optional[str] = None        # 'tushare' | 'static'


def _load_trade_dates() -> set:
    """
    加载交易日集合（带缓存）。
    优先从 Tushare trade_cal 拉取（权威），失败则降级到静态节假日+周末。
    end_date 已动态计算（当前年+5），无需手动维护。
    ⚠️ CN_HOLIDAYS 静态表仅用于 Tushare 不可用时的降级，需按年补充。
    """
    global _trade_dates_cache, _cache_source
    if _trade_dates_cache is not None:
        return _trade_dates_cache

    try:
        from data_sources.tushare_source import TushareSource
        ts = TushareSource()
        # 动态上界：当前年份 + 5 年（交易所通常提前 1~2 年公布日历）
        _cal_end = str(date.today().year + 5) + '1231'
        df = ts.pro.trade_cal(
            start_date='20200101', end_date=_cal_end,
            is_open='1',
            fields='cal_date',
        )
        if df is not None and not df.empty:
            _trade_dates_cache = {
                f'{d[:4]}-{d[4:6]}-{d[6:8]}'
                for d in df['cal_date'].astype(str).tolist()
            }
            _cache_source = 'tushare'
            return _trade_dates_cache
    except Exception as e:
        log.debug("tushare_trade_cal_unavailable", error=str(e)[:80])

    # 降级：空集合，标记为静态模式
    _trade_dates_cache = set()
    _cache_source = 'static'
    return _trade_dates_cache


def is_non_trade_date(date_str: str) -> bool:
    """
    判断日期是否为非交易日（唯一权威入口）。
    Tushare 缓存模式：直接查 set（覆盖周末+节假日+补班日）。
    降级模式：周末 + 静态节假日。
    """
    from datetime import datetime
    trade_dates = _load_trade_dates()
    if _cache_source == 'tushare' and trade_dates:
        return date_str[:10] not in trade_dates
    # 降级
    try:
        dt = datetime.strptime(date_str[:10], '%Y-%m-%d')
        return dt.weekday() >= 5 or date_str[:10] in CN_HOLIDAYS
    except ValueError:
        return False


def resolve_end_date(end_date: Optional[str] = None, fmt: str = "%Y-%m-%d") -> str:
    """
    将 end_date 校正到最近有数据的交易日。
    核心规则：盘前（数据未发布时）自动回退到上一个交易日。
    end_date=None 时默认用今天。所有同步模块的统一入口。
    """
    _today = date.today()
    if end_date is None:
        _end_dt = _today
    else:
        # 兼容 YYYYMMDD 和 YYYY-MM-DD 两种格式
        clean = end_date.replace("-", "")[:8]
        _end_dt = date(int(clean[:4]), int(clean[4:6]), int(clean[6:8]))
        if _end_dt > _today:
            _end_dt = _today    # 未来日期截断到今天（不可能有未来数据）

    # 向前回退到最近交易日（最多 15 天，覆盖春节最长假期）
    for _ in range(15):
        if not is_non_trade_date(_end_dt.strftime("%Y-%m-%d")):
            break
        _end_dt -= timedelta(days=1)

    # 盘前回退：今天是交易日但数据尚未发布 → 回退到上一个交易日
    if _end_dt == _today:
        from datetime import datetime
        from settings import MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE
        now = datetime.now()
        data_not_ready = (
            now.hour < MARKET_CLOSE_HOUR
            or (now.hour == MARKET_CLOSE_HOUR and now.minute < MARKET_CLOSE_MINUTE)
        )
        if data_not_ready:
            _end_dt -= timedelta(days=1)
            for _ in range(15):
                if not is_non_trade_date(_end_dt.strftime("%Y-%m-%d")):
                    break
                _end_dt -= timedelta(days=1)
            log.info("end_date_pre_market_rollback",
                     today=_today.strftime("%Y-%m-%d"),
                     resolved=_end_dt.strftime(fmt))

    resolved = _end_dt.strftime(fmt)
    if end_date and resolved != end_date:
        log.info("end_date_resolved", original=end_date, resolved=resolved)
    return resolved


def _fallback_date(fmt: str = "%Y-%m-%d") -> str:
    """系统日期回退到最近交易日（resolve_end_date 的别名）"""
    return resolve_end_date(None, fmt)


def get_table_latest_date(table: str = "bars", fmt: str = "%Y-%m-%d") -> str | None:
    """获取指定资产表的最新 trade_date（统一入口）。"""
    r = get_table_date_range(table, fmt)
    return r[1] if r else None


def get_table_date_range(table: str = "bars", fmt: str = "%Y-%m-%d") -> tuple[str, str] | None:
    """获取指定资产表的 (最早, 最晚) trade_date。空表返回 None。"""
    from core.database import db_session
    from sqlalchemy import func as sqlfunc
    from models.quant_data import (
        StockDailyBar, StockDailyFactor, StockMoneyFlow,
        IndustryIndexDaily, EtfDailyBar,
        ConvertibleBondBar, ConvertibleBondFactor,
    )

    _models = {
        "bars": StockDailyBar,
        "factors": StockDailyFactor,
        "money_flow": StockMoneyFlow,
        "industry": IndustryIndexDaily,
        "etf": EtfDailyBar,
        "bond_bar": ConvertibleBondBar,
        "bond_factor": ConvertibleBondFactor,
    }
    model = _models.get(table)
    if not model:
        raise ValueError(f"未知表类型 '{table}'，可选: {list(_models.keys())}")

    with db_session() as db:
        row = db.query(sqlfunc.min(model.trade_date), sqlfunc.max(model.trade_date)).one()
    if row[0] and row[1]:
        return _parse_date(row[0]).strftime(fmt), _parse_date(row[1]).strftime(fmt)
    return None


def _parse_date(value) -> date:
    """将各种日期格式统一解析为 date 对象"""
    if isinstance(value, date):
        return value
    s = str(value).replace("-", "")[:8]
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def get_verified_trade_date(asset_type: str = "stock", fmt: str = "%Y-%m-%d",
                            min_ratio: float = 0.6):
    """
    获取经过完整度验证的最新交易日。

    逻辑：取 max(trade_date)，若该日期的记录数 < min_ratio × 预期标的数，
    则回退到前一个有数据的交易日，最多回退 5 天。

    Args:
        asset_type: "stock" | "etf" | "bond"
        fmt: 返回日期格式
        min_ratio: 最低完整率（0～1），默认 60%

    Returns:
        (date_str, is_verified) 元组
        is_verified=True 表示通过完整度校验
    """
    try:
        from core.database import db_session
        from sqlalchemy import func as sqlfunc

        with db_session() as db:
            if asset_type == "etf":
                from models.quant_data import EtfBasicInfo, EtfDailyBar
                bar_model = EtfDailyBar
                expected = db.query(sqlfunc.count(EtfBasicInfo.code)).filter(
                    EtfBasicInfo.is_active == True
                ).scalar() or 0
            elif asset_type == "bond":
                from sqlalchemy import text as sa_text
                from models.quant_data import ConvertibleBondBar
                bar_model = ConvertibleBondBar
                # 用最近30天有过交易的可转债数作为基数（而非全部 listed，
                # 因为大量停牌/极低流动性的可转债从未有行情数据）
                expected = db.execute(sa_text(
                    "SELECT COUNT(DISTINCT code) FROM convertible_bond_bar "
                    "WHERE trade_date >= date((SELECT MAX(trade_date) FROM convertible_bond_bar), '-30 days')"
                )).scalar() or 0
            else:
                from models.quant_data import StockDailyBar, StockBasicInfo
                bar_model = StockDailyBar
                expected = db.query(sqlfunc.count(StockBasicInfo.code)).filter(
                    StockBasicInfo.is_active == True
                ).scalar() or 0

            if expected == 0:
                # 无预期，降级用裸 max
                max_dt = db.query(sqlfunc.max(bar_model.trade_date)).scalar()
                if max_dt:
                    return _parse_date(max_dt).strftime(fmt), False
                return _fallback_date(fmt), False

            # 取最近 6 个交易日
            recent = [r[0] for r in (
                db.query(bar_model.trade_date)
                .distinct()
                .order_by(bar_model.trade_date.desc())
                .limit(6).all()
            )]
            if not recent:
                return _fallback_date(fmt), False

            for dt in recent:
                cnt = db.query(sqlfunc.count(sqlfunc.distinct(bar_model.code))).filter(
                    bar_model.trade_date == dt
                ).scalar() or 0
                ratio = cnt / expected
                if ratio >= min_ratio:
                    return _parse_date(dt).strftime(fmt), True

            # 全部不达标，返回最新的但标记为未验证
            return _parse_date(recent[0]).strftime(fmt), False

    except Exception as e:
        log.warning("get_verified_trade_date_failed", asset_type=asset_type, error=str(e))
        return _fallback_date(fmt), False

