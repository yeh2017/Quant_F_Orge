"""
每日信号生成
============
同步完成后自动调用，对全市场活跃股票做因子打分，
Top 结果写入 FactorSnapshot 表供前端展示。
"""

import time
import structlog
from datetime import date, timedelta
from typing import Optional

log = structlog.get_logger("signal_job")


def generate_daily_signals(trade_date: Optional[str] = None, top_n: int = 50,
                           universe_filters: Optional[dict] = None):
    """
    全市场因子打分 → 写入 FactorSnapshot。

    Args:
        trade_date: 基准日期（默认今天或最近交易日）
        top_n: 保存前 N 只到快照表（默认 50）
        universe_filters: 投资域过滤参数
            exclude_st: 排除 ST/*ST（默认 True）
            min_list_days: 最短上市天数（默认 60）
    """
    t0 = time.time()
    filters = universe_filters or {}
    exclude_st = filters.get("exclude_st", True)
    min_list_days = filters.get("min_list_days", 60)

    # 日期处理：统一从工具函数获取（优先 DB 最新行情日期）
    if not trade_date:
        from utils.trade_date import get_table_latest_date
        trade_date = get_table_latest_date("bars")
        if not trade_date:
            log.warning("daily_signal_no_data")
            return []

    log.info("daily_signal_start", trade_date=trade_date)

    try:
        # 读取全市场活跃股票（带名称和上市日期，用于投资域过滤）
        from core.database import db_session
        from models.quant_data import StockBasicInfo
        codes = []
        with db_session() as db:
            rows = db.query(
                StockBasicInfo.code, StockBasicInfo.name, StockBasicInfo.list_date
            ).filter(
                StockBasicInfo.is_active == True
            ).all()

            cutoff_date = None
            if min_list_days > 0:
                cutoff_date = (date.fromisoformat(trade_date) - timedelta(days=min_list_days)).strftime("%Y-%m-%d")

            for r in rows:
                # 排除北交所（4/8/9开头），流动性差不适合因子分析
                if r.code[0] in ("4", "8", "9"):
                    continue
                # 排除 ST / *ST
                if exclude_st and r.name and "ST" in r.name.upper():
                    continue
                # 排除退市股（Tushare list_status 可能延迟，名字兜底）
                if r.name and "退市" in r.name:
                    continue
                # 排除次新股（上市不足 min_list_days 天）
                if cutoff_date and r.list_date and r.list_date > cutoff_date:
                    continue
                codes.append(r.code)

        if not codes:
            log.warning("daily_signal_no_stocks")
            return []

        log.info("daily_signal_stocks", count=len(codes))

        # 计算日期范围（最近 60 天用于因子计算）
        end_dt = date.fromisoformat(trade_date)
        start_dt = end_dt - timedelta(days=60)
        start_date = start_dt.strftime("%Y-%m-%d")

        # 调用向量化因子打分
        from services.stock_service import StockService
        from services.factor_service import FactorService
        fs = FactorService(StockService())
        results = fs.calculate_factor_scores_fast(
            codes, start_date, trade_date
        )

        if not results:
            log.warning("daily_signal_empty_results")
            return []

        # 全量写入快照（选股器/回测可直接读取，避免重算）
        fs._save_snapshot(results, trade_date)

        elapsed = round(time.time() - t0, 1)
        log.info(
            "daily_signal_done",
            total=len(results),
            top1=results[0]["code"] if results else "N/A",
            top1_score=round(results[0].get("composite", 0), 3) if results else 0,
            seconds=elapsed,
        )

        return results[:top_n]

    except Exception as e:
        log.error("daily_signal_failed", error=str(e))
        raise
