"""
融资融券同步
============
同步最新交易日的融资融券明细（个股级）。
来源: Tushare margin_detail（需 5000 积分）
特点: 按日期拉全市场（~1600 只两融标的），单次 API <2s
"""

import time
import structlog
import pandas as pd
from typing import Optional

from core.database import db_session
from jobs.sync_base import write_watermark
from utils.trade_date import resolve_end_date

log = structlog.get_logger("sync_margin")


def sync_margin(ts_source, start_date: Optional[str] = None,
                end_date: Optional[str] = None,
                force_refill: bool = False,
                task_id: Optional[str] = None) -> dict:
    """
    同步融资融券明细。

    日常模式：基于 DB 实际最大日期自动回补到最新交易日。
    force_refill：按 start_date~end_date 逐交易日拉取。

    关键设计：
    - 不信任水位，以 DB 实际数据为准（防止 T+1 延迟导致虚假水位推进）
    - 只有实际写入数据时才推进水位（0 条 → 水位不动）
    """
    t_start = time.time()

    if force_refill and start_date and end_date:
        s = start_date.replace("-", "")[:8]
        e = end_date.replace("-", "")[:8]
        total = _sync_margin_range(ts_source, s, e)
        wm_date_raw = e
    else:
        target_date = resolve_end_date(fmt="%Y%m%d")
        # 基于 DB 实际最大日期 +1 回补，不信任水位
        db_next = _get_db_max_next("stock_margin_data")
        if db_next and db_next < target_date:
            log.info("margin_backfill", from_date=db_next, to_date=target_date)
            total = _sync_margin_range(ts_source, db_next, target_date)
        else:
            total = _sync_margin_day(ts_source, target_date)
        wm_date_raw = target_date

    duration = round(time.time() - t_start, 1)

    # 只有实际写入数据时才推进水位，避免虚假水位导致空洞
    if total > 0:
        # 水位设为 DB 实际最大日期（不是 target_date）
        actual_max = _get_db_max_date("stock_margin_data") or wm_date_raw
        write_watermark("margin", "any", actual_max, t_start, "success")
        log.info("sync_margin_done", rows=total, watermark=actual_max, duration=duration)
    else:
        log.info("sync_margin_done", rows=0, watermark="unchanged", duration=duration)

    return {"rows": total}


def _sync_margin_day(ts_source, target_date: str) -> int:
    """拉取单日融资融券"""
    try:
        import data_sources.tushare_source as tushare_module

        @tushare_module.with_tushare_retry(max_retries=2, delay=2.0)
        def _fetch():
            return ts_source.pro.margin_detail(
                trade_date=target_date,
                fields="ts_code,trade_date,rzye,rzmre,rqye,rzrqye"
            )

        df = _fetch()
        if df is None or df.empty:
            log.warning("margin_detail_empty", trade_date=target_date)
            return 0

        tushare_module.validate_tushare_fields(
            df, ["ts_code", "trade_date", "rzye"], api_name="margin_detail"
        )
        return _upsert_margin(df)

    except Exception as e:
        log.error("sync_margin_day_failed", trade_date=target_date, error=str(e))
        return 0


def _sync_margin_range(ts_source, start: str, end: str) -> int:
    """force_refill：按交易日逐日拉取（单次 API 上限 6000 行 ≈ 4 个交易日）"""
    import time as _t
    trade_dates = _get_trade_dates(ts_source, start, end)
    total = 0
    for td in trade_dates:
        total += _sync_margin_day(ts_source, td)
        _t.sleep(0.15)
    log.info("margin_range_done", days=len(trade_dates), rows=total)
    return total


def _get_db_max_next(table_name: str) -> str | None:
    """读取 DB 实际最大 trade_date +1 天，返回 YYYYMMDD 格式。表空返回 None。

    不信任水位——水位可能因 T+1 延迟写入了虚假值。
    以 DB 实际数据为唯一真相源。
    """
    from datetime import timedelta
    from sqlalchemy import text
    try:
        with db_session() as db:
            r = db.execute(text(
                f"SELECT MAX(trade_date) FROM {table_name}"
            )).scalar()
            if r:
                max_date = pd.to_datetime(str(r))
                next_day = max_date + timedelta(days=1)
                return next_day.strftime("%Y%m%d")
    except Exception as e:
        log.debug("db_max_read_error", table=table_name, error=str(e))
    return None


def _get_db_max_date(table_name: str) -> str | None:
    """读取 DB 实际最大 trade_date，返回 YYYY-MM-DD 格式（写水位用）。"""
    from sqlalchemy import text
    try:
        with db_session() as db:
            r = db.execute(text(
                f"SELECT MAX(trade_date) FROM {table_name}"
            )).scalar()
            if r:
                return str(r)[:10]  # Date or str → YYYY-MM-DD
    except Exception as e:
        log.debug("db_max_read_error", table=table_name, error=str(e))
    return None


def _get_trade_dates(ts_source, start: str, end: str) -> list:
    """获取范围内的交易日列表"""
    try:
        df = ts_source.pro.trade_cal(
            start_date=start, end_date=end, is_open="1", fields="cal_date"
        )
        if df is not None and not df.empty:
            return sorted(df["cal_date"].astype(str).tolist())
    except Exception as e:
        log.warning("trade_cal_failed", error=str(e))
    return []


def _upsert_margin(df: pd.DataFrame) -> int:
    """批量 upsert 融资融券明细"""
    from sqlalchemy import text

    written = 0
    with db_session() as db:
        for _, row in df.iterrows():
            try:
                ts_code = str(row.get("ts_code", ""))
                # 转换代码格式: 000001.SZ → 000001.SZ（保持 Tushare 格式）
                code = ts_code

                trade_date = str(row.get("trade_date", ""))
                if len(trade_date) == 8:
                    trade_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"

                if not code or not trade_date:
                    continue

                def _safe_float(v):
                    if v is None:
                        return None
                    try:
                        return float(v)
                    except (ValueError, TypeError):
                        return None

                db.execute(text("""
                    INSERT INTO stock_margin_data (code, trade_date, rzye, rzmre, rqye, rzrqye)
                    VALUES (:code, :trade_date, :rzye, :rzmre, :rqye, :rzrqye)
                    ON CONFLICT(code, trade_date) DO UPDATE SET
                        rzye=excluded.rzye,
                        rzmre=excluded.rzmre,
                        rqye=excluded.rqye,
                        rzrqye=excluded.rzrqye
                """), {
                    "code": code,
                    "trade_date": trade_date,
                    "rzye": _safe_float(row.get("rzye")),
                    "rzmre": _safe_float(row.get("rzmre")),
                    "rqye": _safe_float(row.get("rqye")),
                    "rzrqye": _safe_float(row.get("rzrqye")),
                })
                written += 1
            except Exception as e:
                log.debug("margin_row_skip", error=str(e))

    return written
