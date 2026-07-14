"""
自动清理任务
============
职责：
1. 数据库历史数据清理（保留 7 年）
2. 缓存文件清理（保留 7 天）
3. 临时文件 / __pycache__ / 过期日志清理

调用方式：
  - 后端启动时注册到 BackgroundTasks / APScheduler
  - 每天凌晨 2 点执行一次
"""

import shutil
import pathlib
import structlog
from datetime import datetime, timedelta

log = structlog.get_logger("cleanup_job")

from settings import DB_RETAIN_YEARS, CACHE_RETAIN_DAYS, LOG_RETAIN_DAYS, BACKTEST_RESULT_RETAIN_DAYS, NEWS_RETAIN_DAYS


def cleanup_database(retain_years: int = DB_RETAIN_YEARS) -> dict:
    """
    清理数据库中超过 retain_years 年的历史数据。
    清理表：stock/etf/bond 日线行情 + 因子 + 资金流向 + 融资融券 + 事件 + 回测
    不清理：basic_info / financials / shareholder_count（基本面数据量小，全量保留）
    """
    from core.database import db_session
    from models.quant_data import (
        StockDailyBar, StockDailyFactor, StockMoneyFlow, StockMarginData, StockNews,
        EtfDailyBar, EtfBasicInfo, ConvertibleBondBar, ConvertibleBondFactor,
        IndustryIndexDaily, FactorSnapshot, EtfFundSnapshot,
        StockShareholderCount,
    )
    from models.all_models import BacktestResult

    cutoff = (datetime.now() - timedelta(days=retain_years * 365)).strftime("%Y-%m-%d")
    stats = {}
    with db_session() as db:
        try:
            # ── 股票 ──
            stats["stock_daily_bars"] = db.query(StockDailyBar)\
                .filter(StockDailyBar.trade_date < cutoff)\
                .delete(synchronize_session=False)

            stats["stock_daily_factors"] = db.query(StockDailyFactor)\
                .filter(StockDailyFactor.trade_date < cutoff)\
                .delete(synchronize_session=False)

            stats["stock_money_flow"] = db.query(StockMoneyFlow)\
                .filter(StockMoneyFlow.trade_date < cutoff)\
                .delete(synchronize_session=False)

            stats["stock_margin_data"] = db.query(StockMarginData)\
                .filter(StockMarginData.trade_date < cutoff)\
                .delete(synchronize_session=False)

            # ── ETF ──
            stats["etf_daily_bars"] = db.query(EtfDailyBar)\
                .filter(EtfDailyBar.trade_date < cutoff)\
                .delete(synchronize_session=False)

            stats["etf_fund_snapshot"] = db.query(EtfFundSnapshot)\
                .filter(EtfFundSnapshot.trade_date < cutoff)\
                .delete(synchronize_session=False)

            # 孤儿清理：snapshot/bar 中存在但 basic_info 中不存在的 ETF（清盘/退市残留）
            active_codes = set(r[0] for r in db.query(EtfBasicInfo.code).all())
            if active_codes:
                snap_orphans = set(r[0] for r in db.query(EtfFundSnapshot.code.distinct()).all()) - active_codes
                bar_orphans = set(r[0] for r in db.query(EtfDailyBar.code.distinct()).all()) - active_codes
                orphan_del = 0
                if snap_orphans:
                    orphan_del += db.query(EtfFundSnapshot)\
                        .filter(EtfFundSnapshot.code.in_(list(snap_orphans)))\
                        .delete(synchronize_session=False)
                if bar_orphans:
                    orphan_del += db.query(EtfDailyBar)\
                        .filter(EtfDailyBar.code.in_(list(bar_orphans)))\
                        .delete(synchronize_session=False)
                if orphan_del:
                    stats["etf_orphan_cleanup"] = orphan_del

            # ── 可转债 ──
            stats["convertible_bond_bar"] = db.query(ConvertibleBondBar)\
                .filter(ConvertibleBondBar.trade_date < cutoff)\
                .delete(synchronize_session=False)

            stats["convertible_bond_factor"] = db.query(ConvertibleBondFactor)\
                .filter(ConvertibleBondFactor.trade_date < cutoff)\
                .delete(synchronize_session=False)

            # ── 行业指数 + 评分快照 ──
            stats["industry_index_daily"] = db.query(IndustryIndexDaily)\
                .filter(IndustryIndexDaily.trade_date < cutoff)\
                .delete(synchronize_session=False)

            stats["factor_snapshot"] = db.query(FactorSnapshot)\
                .filter(FactorSnapshot.trade_date < cutoff)\
                .delete(synchronize_session=False)

            # ── 股东户数 ──
            stats["stock_shareholder_count"] = db.query(StockShareholderCount)\
                .filter(StockShareholderCount.end_date < cutoff)\
                .delete(synchronize_session=False)

            # ── 新闻：结构化事件按 DB_RETAIN_YEARS，普通新闻按 NEWS_RETAIN_DAYS ──
            stats["structured_events"] = db.query(StockNews)\
                .filter(StockNews.created_at < cutoff,
                        StockNews.nlp_reason.like("[规则]%"))\
                .delete(synchronize_session=False)

            from sqlalchemy import or_
            news_cutoff = datetime.now() - timedelta(days=NEWS_RETAIN_DAYS)
            stats["old_news"] = db.query(StockNews)\
                .filter(StockNews.created_at < news_cutoff,
                        or_(StockNews.nlp_reason.is_(None), ~StockNews.nlp_reason.like("[规则]%")))\
                .delete(synchronize_session=False)

            # ── 回测结果 ──
            bt_cutoff = datetime.now() - timedelta(days=BACKTEST_RESULT_RETAIN_DAYS)
            stats["backtest_results"] = db.query(BacktestResult)\
                .filter(BacktestResult.created_at < bt_cutoff)\
                .delete(synchronize_session=False)

            log.info("db_cleanup_done", cutoff=cutoff, stats=stats)
        except Exception as e:
            log.error("db_cleanup_failed", error=str(e))
            raise  # db_session 会 rollback
    return stats


def cleanup_cache(retain_days: int = CACHE_RETAIN_DAYS) -> int:
    """清理 cache_data/ 目录下超过 retain_days 天的 .pkl 缓存文件"""
    from utils.cache_manager import cache_manager
    cache_manager.cleanup_expired(max_age_days=retain_days)

    # 清理 routers/factors.py 的 TTL 内存缓存（过期条目）
    try:
        from routers.factors import _factor_cache, _factor_cache_lock, _FACTOR_TTL
        import time as _time
        now = _time.time()
        with _factor_cache_lock:
            expired_keys = [
                k for k, entry in list(_factor_cache.items())
                if now - entry.get('ts', 0) > _FACTOR_TTL
            ]
            for k in expired_keys:
                del _factor_cache[k]
        if expired_keys:
            log.info("memory_cache_cleanup", expired=len(expired_keys))
        return len(expired_keys)
    except Exception:
        return 0


def cleanup_files(base_dir: str = None) -> dict:
    """
    清理项目中的临时文件：
    - __pycache__ 目录
    - *.pyc 文件
    - logs/ 下超过 LOG_RETAIN_DAYS 天的日志
    - tmp/ 下的临时文件
    """
    if base_dir is None:
        base_dir = str(pathlib.Path(__file__).parent.parent)

    root = pathlib.Path(base_dir)
    stats = {"pycache": 0, "pyc": 0, "old_logs": 0, "tmp_files": 0}
    cutoff_ts = __import__("time").time() - LOG_RETAIN_DAYS * 86400

    for item in root.rglob("__pycache__"):
        if item.is_dir() and ".venv" not in str(item):
            try:
                shutil.rmtree(item)
                stats["pycache"] += 1
            except Exception:
                pass

    for item in root.rglob("*.pyc"):
        if ".venv" not in str(item):
            try:
                item.unlink()
                stats["pyc"] += 1
            except Exception:
                pass

    # 清理 logs/ 目录下的旧日志
    log_dir = root / "logs"
    if log_dir.exists():
        for f in log_dir.glob("*.log"):
            try:
                if f.stat().st_mtime < cutoff_ts:
                    f.unlink()
                    stats["old_logs"] += 1
            except Exception:
                pass

    # 清理 tmp/ 临时文件（后端自己生成的，不动系统 C:\tmp）
    tmp_dir = root / "tmp"
    if tmp_dir.exists():
        for f in tmp_dir.iterdir():
            try:
                if f.is_file():
                    f.unlink()
                    stats["tmp_files"] += 1
                elif f.is_dir():
                    shutil.rmtree(f)
                    stats["tmp_files"] += 1
            except Exception:
                pass

    log.info("file_cleanup_done", stats=stats)
    return stats


def run_all_cleanups() -> dict:
    """
    一键运行所有清理任务（每日2:00 AM 由调度器调用）
    """
    log.info("cleanup_start", time=datetime.now().isoformat())

    results = {
        "db": cleanup_database(),
        "cache_expired_entries": cleanup_cache(),
        "files": cleanup_files(),
        "timestamp": datetime.now().isoformat(),
    }

    # 清理内存中已完成的旧任务（防止无限膨胀）
    try:
        from utils.task_store import task_store
        task_store.cleanup_old_tasks(max_age_seconds=3600)
    except Exception:
        pass



    log.info("cleanup_all_done", summary={
        "db_rows_deleted": sum(results["db"].values()),
        "cache_entries_cleared": results["cache_expired_entries"],
        "pycache_dirs": results["files"]["pycache"],
    })
    return results
