"""
情绪因子同步
===========
资金流向 + 股东户数
"""

import time
import structlog
import pandas as pd
from datetime import datetime

from core.database import db_session
from jobs.sync_base import write_watermark
from settings import MONEYFLOW_SLEEP

log = structlog.get_logger("sync_sentiment")


# ================================================================
#  独立入口：可被 full_sync 的 SyncStep 单独调用
#  每个函数有独立水位，skip 间隔由 data_sync_service 控制
# ================================================================

def sync_moneyflow_only(ts_source, sent_writer, codes: list,
                        start_date: str, end_date: str, force_refill: bool = False):
    """仅同步资金流向（每日更新）"""
    t0 = time.time()
    rows = _sync_moneyflow(ts_source, sent_writer, codes, start_date, end_date, force_refill)
    # 只有实际写入数据时才推进水位，避免 IP 超限/权限不足导致虚标
    if rows > 0:
        # 用 DB 实际最大日期写水位（非请求 end_date），避免数据未就绪时水位虚高
        try:
            from sqlalchemy import text as _text
            with db_session() as _db:
                _r = _db.execute(_text(
                    "SELECT MAX(trade_date) FROM stock_money_flow"
                )).fetchone()
                actual_max = str(_r[0]).replace("-", "")[:8] if _r and _r[0] else end_date
        except Exception:
            actual_max = end_date
        write_watermark("moneyflow", "any", actual_max, t0, "success")
    else:
        log.warning("moneyflow_no_data_watermark_skip")
    return {"rows": rows}




def sync_shareholder_only(ts_source, sent_writer, codes: list, force_refill: bool = False):
    """仅同步股东户数（季度更新）"""
    t0 = time.time()
    _sync_shareholder_counts(ts_source, sent_writer, codes, force_refill)
    write_watermark("shareholder", "any", None, t0, "success")


def _sync_moneyflow(ts_source, sent_writer, codes: list, start_date: str, end_date: str,
                    force_refill: bool = False):
    """同步资金流向"""
    import data_sources.tushare_source as tushare_module
    target_set = set(codes)

    try:
        @tushare_module.with_tushare_retry(max_retries=2, delay=1.0)
        def _fetch_cal():
            return ts_source.pro.trade_cal(
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                is_open="1",
            )
        df_cal = _fetch_cal()
        if df_cal is not None and not df_cal.empty:
            all_dates = sorted(df_cal["cal_date"].tolist())
            trade_dates = all_dates if force_refill else all_dates[-5:]
        else:
            trade_dates = [end_date.replace("-", "")]
    except Exception:
        trade_dates = [end_date.replace("-", "")]

    total = len(trade_dates)
    log.info("moneyflow_dates_to_sync", count=total, force_refill=force_refill,
             first=trade_dates[0] if trade_dates else None,
             last=trade_dates[-1] if trade_dates else None)

    inserted_rows = 0
    consecutive_empty = 0
    from settings import TUSHARE_BREAKER_FAIL_THRESHOLD
    BAIL_THRESHOLD = TUSHARE_BREAKER_FAIL_THRESHOLD
    day_idx = 0

    for day_idx, td in enumerate(trade_dates):
        try:
            @tushare_module.with_tushare_retry(max_retries=1, delay=1.0)
            def _fetch_mf():
                return ts_source.pro.moneyflow(trade_date=td)

            df_mf = _fetch_mf()
            if df_mf is not None and not df_mf.empty:
                consecutive_empty = 0
                trade_date_obj = pd.to_datetime(td, format="%Y%m%d").date()
                with db_session() as db:
                    n = sent_writer.upsert_moneyflow_batch(db, df_mf, trade_date_obj, target_set)
                    inserted_rows += (n or len(df_mf))
            else:
                consecutive_empty += 1
                log.debug("moneyflow_empty_day", trade_date=td, consecutive=consecutive_empty)
                if consecutive_empty >= BAIL_THRESHOLD:
                    log.warning("moneyflow_bail_out",
                                reason="连续空数据，疑似积分不足",
                                consecutive=consecutive_empty,
                                last_date=td, inserted_so_far=inserted_rows)
                    break
            time.sleep(MONEYFLOW_SLEEP)
        except Exception as e:
            err = str(e)
            if "权限" in err or "积分" in err or "限制" in err:
                log.warning("moneyflow_permission_denied", error=err)
                break
            log.warning("moneyflow_fetch_failed", trade_date=td, error=err)
            time.sleep(MONEYFLOW_SLEEP)

    log.info("moneyflow_sync_done", inserted=inserted_rows, dates=total,
             processed=day_idx + 1 if trade_dates else 0)
    return inserted_rows




def _sync_shareholder_counts(ts_source, sent_writer, codes: list, force_refill: bool = False):
    """同步股东户数（增量策略：只拉最近 30 天内未更新的股票，force_refill 时全量）"""
    import data_sources.tushare_source as tushare_module
    from models.quant_data import StockShareholderCount
    from datetime import timedelta
    success = 0

    # 增量：查询已有最新更新日期，跳过近 30 天内已更新的
    skip_codes = set()
    if not force_refill:
        cutoff = (datetime.now() - timedelta(days=30)).date()
        try:
            from sqlalchemy import func as sqlfunc
            with db_session() as db:
                rows = db.query(
                    StockShareholderCount.code,
                    sqlfunc.max(StockShareholderCount.end_date),
                ).group_by(StockShareholderCount.code).all()
                for code, last_date in rows:
                    if last_date and last_date >= cutoff:
                        skip_codes.add(code)
        except Exception:
            pass  # 查询失败则全量拉取

    need_sync = [c for c in codes if c not in skip_codes]
    log.info("shareholder_incremental",
             total=len(codes), skip=len(skip_codes), need_sync=len(need_sync))

    for code in need_sync:
        try:
            @tushare_module.with_tushare_retry(max_retries=1, delay=1.0)
            def _fetch_holder():
                return ts_source.pro.stk_holdernumber(ts_code=code)

            df = _fetch_holder()
            if df is not None and not df.empty:
                records = []
                # Tushare stk_holdernumber 返回按 end_date 降序，iloc[0]=最新期
                top_rows = df.head(5)  # 取5行：前4行计算，第5行作为第4行的前一期
                holder_nums = top_rows["holder_num"].fillna(0).astype(int).tolist()
                for idx, (_, row) in enumerate(top_rows.head(4).iterrows()):
                    end_date_str = str(row.get("end_date", ""))
                    end_date_parsed = pd.to_datetime(end_date_str, format="%Y%m%d", errors="coerce")
                    if pd.isna(end_date_parsed):
                        continue
                    holder_num = holder_nums[idx]
                    change_rate = 0.0
                    # 与紧邻的下一期（更旧一期）比较
                    if idx + 1 < len(holder_nums):
                        prev_num = holder_nums[idx + 1]
                        if prev_num > 0:
                            change_rate = (holder_num - prev_num) / prev_num * 100
                    records.append({
                        "code": code,
                        "end_date": end_date_parsed.date(),
                        "holder_num": holder_num,
                        "holder_num_change_rate": round(change_rate, 2),
                    })
                if records:
                    with db_session() as db:
                        sent_writer.upsert_shareholder_batch(db, records)
                    success += 1

            time.sleep(0.15)
        except Exception as e:
            err_str = str(e)
            if "权限" in err_str or "积分" in err_str:
                log.warning("shareholder_api_unavailable", error=err_str)
                break
            continue

    log.info("shareholder_sync_done", success=success)

