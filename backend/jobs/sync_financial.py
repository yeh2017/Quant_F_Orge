"""
财务数据同步
===========
Tushare fina_indicator → Baostock fallback → 写入 stock_financials
"""

import time
import structlog
import pandas as pd
from typing import List, Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.database import db_session
from jobs.sync_base import report_progress, write_watermark
from settings import FINANCIAL_WORKERS, FINANCIAL_SLEEP

log = structlog.get_logger("sync_financial")


def sync_financial(ts_source, fin_writer, codes: List[str],
                   task_id: Optional[str] = None, force_refill: bool = False):
    """同步财务数据（面向 DataSyncService 的函数入口）"""
    log.info("sync_financial_start", count=len(codes), force_refill=force_refill)
    t_start = time.time()
    success_count = 0
    total = len(codes)
    completed_count = 0

    if task_id:
        try:
            from utils.task_store import task_store, TaskStatus
            task_store.update_task(task_id, TaskStatus.RUNNING, result={
                "progress": 0, "total": total,
                "message": f"开始同步财务数据，共 {total} 只股票..."
            })
        except Exception:
            pass

    # ── 第2层跳过：行级增量过滤 ──
    # 第1层跳过在 data_sync_service._should_skip_financial()，按水位判断整个阶段是否跳过。
    # 若进入本函数，说明第1层没跳过。此处做第2层：逐只检查 DB 中的 updated_at，
    # 跳过 90 天内已更新的个股，只拉过期的。两层互不冲突：
    #   第1层 = 财报季外不进入 / 财报季内 7 天执行一次
    #   第2层 = 进入后只拉真正需要更新的个股
    FINANCIAL_SKIP_DAYS = 90
    need_fetch = codes
    if not force_refill:
        try:
            from datetime import timedelta
            cutoff = (datetime.now() - timedelta(days=FINANCIAL_SKIP_DAYS)).strftime("%Y-%m-%d")
            with db_session() as db:
                from sqlalchemy import text as _sa_text
                result = db.execute(_sa_text(
                    "SELECT DISTINCT code FROM stock_financials WHERE updated_at >= :cutoff"
                ), {"cutoff": cutoff})
                already_synced = {row[0] for row in result}
            need_fetch = [c for c in codes if c not in already_synced]
            skipped = total - len(need_fetch)
            if skipped > 0:
                log.info("financial_incremental_skip",
                         skipped=skipped, need_fetch=len(need_fetch),
                         cutoff_days=FINANCIAL_SKIP_DAYS)
                if task_id:
                    report_progress(task_id, 0, len(need_fetch) or 1,
                                    f"增量检测：跳过 {skipped} 只已有近期数据，实际拉取 {len(need_fetch)} 只")
        except Exception as e:
            log.warning("financial_incremental_check_failed", error=str(e))
            need_fetch = codes
    else:
        log.info("financial_force_refill", count=len(codes))

    total = len(need_fetch)
    if total == 0:
        log.info("financial_all_up_to_date", skipped=len(codes))
        if task_id:
            try:
                from utils.task_store import task_store, TaskStatus
                task_store.update_task(task_id, TaskStatus.COMPLETED, result={
                    "progress": 100, "message": f"财务数据均为最新 ✅ ({len(codes)} 只全部跳过)"
                })
            except Exception:
                pass
        return

    error_count = 0
    no_data_count = 0

    with ThreadPoolExecutor(max_workers=FINANCIAL_WORKERS) as executor:
        future_to_code = {
            executor.submit(_fetch_financial, ts_source, code): code
            for code in need_fetch
        }

        for future in as_completed(future_to_code):
            code = future_to_code[future]
            completed_count += 1

            try:
                result_code, df = future.result()
                if df is not None and not df.empty:
                    with db_session() as db:
                        if fin_writer.upsert(db, code, df):
                            success_count += 1
                else:
                    no_data_count += 1
            except Exception as e:
                log.error("financial_write_failed", code=code, error=str(e))
                error_count += 1

            if task_id:
                report_progress(task_id, completed_count, total,
                                f"财务数据: {completed_count}/{total} ({code})")
            if completed_count % 50 == 0:
                log.info("financial_progress", done=completed_count, total=total)

    log.info("sync_financial_done", success=success_count, no_data=no_data_count,
             errors=error_count, total=total)
    # 财务数据全市场只有一份，不区分 all/pool/hs300，固定 mode="any"
    # ⚠️ should_skip 查询时也必须用 mode="any"，参见 data_sync_service._should_skip
    wm_status = "success" if success_count > 0 else "failed"
    write_watermark("financials", "any", None, t_start, wm_status)
    if wm_status == "failed":
        log.warning("financial_zero_success_watermark_failed",
                    total=total, errors=error_count)

    if task_id:
        try:
            from utils.task_store import task_store, TaskStatus
            duration = round(time.time() - t_start, 1)
            if success_count == 0:
                msg = (f"⚠️ 财务数据同步完成但 0 只成功写入 ({total} 只处理，耗时 {duration}s)。"
                       f"可能原因：① Tushare积分不足（fina_indicator需600+）② 网络超时")
            else:
                msg = f"财务数据同步完成 ✅ ({success_count}/{total} 只，耗时 {duration}s)"
            task_store.update_task(task_id, TaskStatus.COMPLETED, result={
                "progress": 100, "total": total, "success": success_count,
                "message": msg,
            })
        except Exception:
            pass


def _fetch_financial(ts_source, code: str):
    """拉取单只股票财务数据（纯函数，无共享状态）"""
    df = None
    tushare_ok = False

    try:
        import data_sources.tushare_source as tushare_module

        @tushare_module.with_tushare_retry(max_retries=1, delay=1.0)
        def _fetch_fina():
            return ts_source.pro.fina_indicator(
                ts_code=code,
                fields="ts_code,ann_date,end_date,roe,roa,grossprofit_margin,"
                       "netprofit_margin,or_yoy,netprofit_yoy,eps",
            )

        df = _fetch_fina()
        if df is not None and not df.empty:
            from data_sources.tushare_source import validate_tushare_fields
            validate_tushare_fields(df,
                ["roe", "roa", "grossprofit_margin", "netprofit_margin", "or_yoy", "netprofit_yoy", "eps"],
                api_name="fina_indicator")
            tushare_ok = True

            # 追加现金流数据（经营活动现金流净额）
            try:
                @tushare_module.with_tushare_retry(max_retries=1, delay=0.5)
                def _fetch_cf():
                    return ts_source.pro.cashflow(
                        ts_code=code,
                        fields="ts_code,end_date,n_cashflow_act",
                    )
                df_cf = _fetch_cf()
                if df_cf is not None and not df_cf.empty:
                    df_cf = df_cf.drop_duplicates(subset=["end_date"], keep="first")
                    df = df.merge(df_cf[["end_date", "n_cashflow_act"]], on="end_date", how="left")
            except Exception as cf_err:
                log.debug("cashflow_fetch_skip", code=code, error=str(cf_err))

            # 追加资产负债率（从 balancesheet 计算）
            try:
                @tushare_module.with_tushare_retry(max_retries=1, delay=0.5)
                def _fetch_bs():
                    return ts_source.pro.balancesheet(
                        ts_code=code,
                        fields="ts_code,end_date,total_hldr_eqy_exc_min_int,total_assets",
                    )
                df_bs = _fetch_bs()
                if df_bs is not None and not df_bs.empty:
                    df_bs = df_bs.drop_duplicates(subset=["end_date"], keep="first")
                    # 资产负债率 = (1 - 股东权益/总资产) × 100
                    equity = pd.to_numeric(df_bs["total_hldr_eqy_exc_min_int"], errors="coerce")
                    assets = pd.to_numeric(df_bs["total_assets"], errors="coerce")
                    df_bs["debt_to_assets"] = ((1.0 - equity / assets) * 100).where(assets > 0)
                    df = df.merge(df_bs[["end_date", "debt_to_assets"]], on="end_date", how="left")
            except Exception as bs_err:
                log.debug("balancesheet_fetch_skip", code=code, error=str(bs_err))

    except Exception as e:
        log.warning("financial_tushare_failed", code=code, error=str(e))

    # Baostock 兜底（不含现金流/资产负债率，仅基础指标）
    if not tushare_ok:
        try:
            from data_sources.baostock_source import BaostockSource
            BaostockSource._login()  # 单例登录，已登录则直接返回
            bs = BaostockSource._bs_module
            short_code = code.split(".")[0] if "." in code else code
            from utils.asset_type import to_bs_code
            bs_code = to_bs_code(short_code)

            now = datetime.now()
            profit_rows = []
            for year_offset in range(2):
                y = now.year - year_offset
                for q in range(4, 0, -1):
                    rs = bs.query_profit_data(code=bs_code, year=y, quarter=q)
                    while rs.error_code == "0" and rs.next():
                        profit_rows.append(rs.get_row_data())
                    if len(profit_rows) >= 4:
                        break
                if len(profit_rows) >= 4:
                    break

            if profit_rows:
                df_profit = pd.DataFrame(profit_rows, columns=rs.fields)
                df = pd.DataFrame({
                    "end_date": df_profit.get("statDate", pd.Series()),
                    "roe": pd.to_numeric(df_profit.get("roeAvg", pd.Series()), errors="coerce"),
                    "netprofit_margin": pd.to_numeric(df_profit.get("npMargin", pd.Series()), errors="coerce"),
                    "grossprofit_margin": pd.to_numeric(df_profit.get("gpMargin", pd.Series()), errors="coerce"),
                    "roa": None,
                    "revenue_yoy": None,
                    "netprofit_yoy": None,
                    "basic_eps": pd.to_numeric(df_profit.get("epsTTM", pd.Series()), errors="coerce"),
                })
        except Exception as e:
            log.warning("financial_baostock_failed", code=code, error=str(e))

    time.sleep(FINANCIAL_SLEEP)
    return code, df

