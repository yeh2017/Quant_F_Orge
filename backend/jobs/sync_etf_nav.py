"""
ETF 净值 + 份额 同步模块
========================
快照模式：每次运行存当天数据，自然积累历史。
数据来源：
  - 净值：Tushare fund_nav（主） → AkShare fund_etf_spot_ths（fallback）
  - 份额：Tushare fund_share（主，一次调用覆盖全市场 ETF）
"""

import time
import structlog
from datetime import date, datetime
from typing import Optional

from core.database import db_session
from jobs.sync_base import write_watermark

log = structlog.get_logger("sync_etf_nav")


def _update_task(task_id, status_or_pct, **kwargs):
    """统一的任务进度上报（best-effort）"""
    if not task_id:
        return
    try:
        from utils.task_store import task_store, TaskStatus
        if isinstance(status_or_pct, int):
            task_store.update_task(task_id, TaskStatus.RUNNING,
                                  result={"progress": status_or_pct, **kwargs})
        else:
            task_store.update_task(task_id, status_or_pct, **kwargs)
    except Exception as _e:
        log.debug("suppressed_error", error=str(_e))




def _ts_to_6(ts_code: str) -> str:
    """Tushare 格式 → 6位（510300.SH → 510300）"""
    return ts_code.split(".")[0] if "." in ts_code else ts_code



# ─── QDII 净值回补 ─── #

def _backfill_delayed_nav(etf_codes, current_date, nav_map, db_session_fn, EtfFundSnapshot, logger):
    """
    QDII 基金净值滞后 T+2 发布。日常同步只拉 nav_date=当天，
    导致 QDII 在 snapshot 中 unit_nav 永远为 None。
    此函数额外拉 T-1、T-2 的 nav_date，回补之前遗漏的记录。
    """
    from datetime import timedelta
    from data_sources.tushare_source import TushareSource
    import data_sources.tushare_source as tushare_module

    # 找出当前 nav_map 中缺净值的 code
    missing_codes = set(etf_codes) - set(nav_map.keys())
    if not missing_codes:
        return

    ts = TushareSource()
    if not ts.pro:
        return

    backfill_count = 0
    for offset in [1, 2]:
        prev_date = current_date - timedelta(days=offset)
        prev_str = prev_date.strftime("%Y%m%d")

        @tushare_module.with_tushare_retry(max_retries=2, delay=1.0)
        def _call(d=prev_str):
            return ts.pro.fund_nav(nav_date=d, market='E')

        try:
            df = _call()
            if df is None or df.empty:
                continue
            with db_session_fn() as db:
                for _, row in df.iterrows():
                    code = str(row.get("ts_code", "")).strip()
                    if code not in missing_codes:
                        continue
                    unit_nav = float(row.get("unit_nav") or 0) or None
                    accum_nav = float(row.get("accum_nav") or 0) or None
                    if not unit_nav:
                        continue

                    # nav_date 是净值归属日期（非公告日）
                    nav_date_str = str(row.get("nav_date", "")).strip()
                    if not nav_date_str:
                        continue
                    from datetime import datetime as _dt
                    nav_dt = _dt.strptime(nav_date_str, "%Y%m%d").date()

                    # 回补对应日期的 snapshot 记录
                    snap = db.query(EtfFundSnapshot).filter_by(
                        code=code, trade_date=nav_dt
                    ).first()
                    if snap and snap.unit_nav is None:
                        snap.unit_nav = unit_nav
                        snap.accum_nav = accum_nav
                        backfill_count += 1
                        missing_codes.discard(code)

            time.sleep(0.3)  # 限频
        except Exception as e:
            logger.debug("backfill_nav_skip", offset=offset, error=str(e)[:60])

    # ── REITs 专用：按 ts_code 查最新净值（净值月/季度发布，nav_date 距今可能数周）──
    if missing_codes:
        from models.quant_data import EtfBasicInfo
        with db_session_fn() as db:
            reit_codes = set(
                r.code for r in db.query(EtfBasicInfo.code).filter(
                    EtfBasicInfo.code.in_(list(missing_codes)),
                    EtfBasicInfo.category == 'REITs',
                ).all()
            )
        if reit_codes:
            consecutive_fails = 0
            for code in reit_codes:
                if consecutive_fails >= 3:
                    logger.warning("reit_nav_abort_too_many_fails",
                                   skipped=len(reit_codes) - backfill_count)
                    break

                @tushare_module.with_tushare_retry(max_retries=1, delay=0.5)
                def _call_reit(c=code):
                    return ts.pro.fund_nav(ts_code=c, limit=1)

                try:
                    df = _call_reit()
                    if df is None or df.empty:
                        continue
                    consecutive_fails = 0  # 成功则重置
                    row = df.iloc[0]
                    unit_nav = float(row.get("unit_nav") or 0) or None
                    accum_nav = float(row.get("accum_nav") or 0) or None
                    if not unit_nav:
                        continue
                    nav_date_str = str(row.get("nav_date", "")).strip()
                    if not nav_date_str:
                        continue
                    from datetime import datetime as _dt
                    nav_dt = _dt.strptime(nav_date_str, "%Y%m%d").date()

                    with db_session_fn() as db:
                        snap = db.query(EtfFundSnapshot).filter_by(
                            code=code, trade_date=nav_dt
                        ).first()
                        if snap:
                            # 有对应日期的 snapshot，仅在 nav 为空时更新
                            if snap.unit_nav is None:
                                snap.unit_nav = unit_nav
                                snap.accum_nav = accum_nav
                                backfill_count += 1
                        else:
                            # nav_date 无 snapshot → 新建（保持日期准确）
                            db.add(EtfFundSnapshot(
                                code=code, trade_date=nav_dt,
                                unit_nav=unit_nav, accum_nav=accum_nav,
                            ))
                            backfill_count += 1
                    time.sleep(0.3)
                except Exception as e:
                    consecutive_fails += 1
                    logger.debug("reit_nav_skip", code=code, error=str(e)[:60])

    if backfill_count:
        logger.info("backfill_delayed_nav_done", filled=backfill_count)


# ─── 数据拉取函数 ─── #

def _fetch_nav_tushare(etf_codes: list[str], trade_date: str) -> dict:
    """
    Tushare fund_nav 按日期批量拉净值。返回 {ts_code: {unit_nav, accum_nav}}
    trade_date 格式 YYYYMMDD
    """
    from data_sources.tushare_source import TushareSource
    import data_sources.tushare_source as tushare_module

    ts = TushareSource()
    result = {}
    etf_set = set(etf_codes)
    if not ts.pro:
        log.warning("nav_tushare_skip_no_pro")
        return result

    # 按日期批量拉（一次返回全市场基金当日净值）
    @tushare_module.with_tushare_retry(max_retries=2, delay=1.0)
    def _call_nav_batch():
        return ts.pro.fund_nav(nav_date=trade_date, market='E')

    try:
        df = _call_nav_batch()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                code = str(row.get("ts_code", "")).strip()
                if code not in etf_set:
                    continue
                unit_nav = float(row.get("unit_nav") or 0) or None
                accum_nav = float(row.get("accum_nav") or 0) or None
                if unit_nav:
                    result[code] = {"unit_nav": unit_nav, "accum_nav": accum_nav}
            log.info("nav_tushare_batch_ok", count=len(result),
                     missed=len(etf_set) - len(result))
    except Exception as e:
        log.warning("nav_tushare_batch_failed", error=str(e)[:80])

    # 未命中的 ETF 由外层 AkShare fallback 兜底（不逐只调 Tushare，避免限频）
    return result


def _fetch_nav_akshare() -> dict:
    """
    AkShare fund_etf_spot_ths 拉全市场 ETF 净值（fallback）。
    返回 {6位code: {unit_nav}}
    """
    import akshare as ak
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(ak.fund_etf_spot_ths)
        df = future.result(timeout=30)

    result = {}
    if df is not None and not df.empty:
        for _, row in df.iterrows():
            code = str(row.get("代码", "")).strip()
            nav = row.get("当前-单位净值")
            if code and nav:
                try:
                    result[code] = {"unit_nav": float(nav)}
                except (ValueError, TypeError):
                    log.debug("nav_akshare_parse_skip", code=code)
    log.info("nav_akshare_fetched", count=len(result))
    return result


def _fetch_share_tushare(etf_codes: list[str], trade_date: str) -> dict:
    """
    Tushare fund_share 按日期批量拉全市场 ETF 份额。
    返回 {ts_code: total_share(份)}
    trade_date 格式 YYYYMMDD
    fd_share 单位是万份，存入时 × 10000 转为份（与下游 etf_service 对齐）
    """
    from data_sources.tushare_source import TushareSource
    import data_sources.tushare_source as tushare_module

    ts = TushareSource()
    etf_set = set(etf_codes)
    result = {}
    if not ts.pro:
        log.warning("share_tushare_skip_no_pro")
        return result

    @tushare_module.with_tushare_retry(max_retries=2, delay=1.0)
    def _call():
        return ts.pro.fund_share(trade_date=trade_date)

    try:
        df = _call()
        if df is not None and not df.empty:
            # 不按 fund_type 过滤——REITs 的 fund_type 为 None，直接用白名单匹配
            for _, row in df.iterrows():
                code = str(row.get('ts_code', '')).strip()
                if code not in etf_set:
                    continue
                fd_share = row.get('fd_share')
                if fd_share and float(fd_share) > 0:
                    result[code] = float(fd_share) * 10000  # 万份 → 份
            log.info("share_tushare_ok", count=len(result),
                     missed=len(etf_set) - len(result))
    except Exception as e:
        log.warning("share_tushare_failed", error=str(e)[:80])

    return result


# ─── 主同步函数 ─── #

def sync_etf_nav_share(task_id: Optional[str] = None,
                       start_date: Optional[str] = None,
                       end_date: Optional[str] = None) -> dict:
    """
    同步 ETF 净值 + 份额快照到 EtfFundSnapshot 表。

    - 日常模式（无 start/end）：快照当天数据，自然积累。
    - 范围模式（有 start/end）：按交易日逐日拉取，用于补历史。
      AkShare 只在日常模式降级（不支持历史日期）。
    """
    from models.quant_data import EtfBasicInfo, EtfFundSnapshot

    log.info("sync_etf_nav_share_start", start=start_date, end=end_date)
    t0 = time.time()
    count = 0
    error_msg = None
    trade_date_str = str(date.today()).replace("-", "")  # 默认值，try 内会覆盖

    _update_task(task_id, 0, message="Step 1: 读取活跃 ETF 列表...")

    try:
        # Step 1: 获取活跃 ETF 列表
        with db_session() as db:
            active_etfs = db.query(EtfBasicInfo.code).filter(
                EtfBasicInfo.is_active == True  # noqa: E712
            ).all()
            etf_codes = [r[0] for r in active_etfs]

        if not etf_codes:
            log.warning("sync_etf_nav_no_active_etfs")
            return {"rows": 0}

        log.info("etf_nav_active_list", count=len(etf_codes))

        # 确定拉取日期列表
        if start_date and end_date:
            # 范围模式：按交易日逐日拉取
            trade_dates = _get_trade_dates_for_range(
                start_date.replace("-", "")[:8],
                end_date.replace("-", "")[:8],
            )
            log.info("etf_nav_range_mode", days=len(trade_dates))
        else:
            # 日常模式：单日
            from utils.trade_date import get_table_latest_date
            bar_latest = get_table_latest_date("etf")
            if bar_latest:
                trade_date_str = bar_latest.replace("-", "")
            else:
                from utils.trade_date import resolve_end_date
                trade_date_str = resolve_end_date(fmt="%Y%m%d")
            trade_dates = [trade_date_str]

        total_days = len(trade_dates)
        share_failed = False  # 追踪份额拉取是否完全失败

        for day_idx, td_str in enumerate(trade_dates, 1):
            try:
                td = datetime.strptime(td_str, "%Y%m%d").date()
                trade_date_str = td_str  # 更新水位用

                pct = round(day_idx / total_days * 100)
                _update_task(task_id, pct,
                             message=f"拉取 {day_idx}/{total_days} 天 ({td_str})...")

                # 拉净值（Tushare）
                nav_map = {}
                try:
                    nav_map = _fetch_nav_tushare(etf_codes, td_str)
                except Exception as ts_err:
                    log.warning("nav_tushare_failed", date=td_str,
                                error=str(ts_err)[:80])

                # AkShare 降级仅在单日模式（AkShare 不支持历史日期）
                if total_days == 1:
                    # QDII 净值滞后 T+2，额外拉 T-1/T-2 回补遗漏
                    _backfill_delayed_nav(etf_codes, td, nav_map, db_session, EtfFundSnapshot, log)

                    missing_nav = len(etf_codes) - len(nav_map)
                    if missing_nav > len(etf_codes) * 0.3:
                        try:
                            ak_nav = _fetch_nav_akshare()
                            for ts_code in etf_codes:
                                if ts_code not in nav_map:
                                    code_6 = _ts_to_6(ts_code)
                                    if code_6 in ak_nav:
                                        nav_map[ts_code] = ak_nav[code_6]
                            log.info("nav_combined", total=len(nav_map))
                        except Exception as ak_err:
                            log.warning("nav_akshare_fallback_failed",
                                        error=str(ak_err)[:80])

                # 拉份额（Tushare）
                share_map = _fetch_share_tushare(etf_codes, td_str)
                if not share_map and len(etf_codes) > 100:
                    share_failed = True
                    log.warning("share_map_empty", date=td_str,
                                etf_count=len(etf_codes))

                # 写入
                all_codes = set(nav_map.keys()) | set(share_map.keys())
                with db_session() as db:
                    for ts_code in all_codes:
                        nav_info = nav_map.get(ts_code, {})
                        share_val = share_map.get(ts_code)
                        unit_nav = nav_info.get("unit_nav")
                        accum_nav = nav_info.get("accum_nav")

                        if not unit_nav and not share_val:
                            continue

                        existing = db.query(EtfFundSnapshot).filter_by(
                            code=ts_code, trade_date=td
                        ).first()

                        vals = dict(
                            code=ts_code, trade_date=td,
                            unit_nav=unit_nav, accum_nav=accum_nav,
                            total_share=share_val,
                        )

                        if existing:
                            for k, v in vals.items():
                                if v is not None:
                                    setattr(existing, k, v)
                        else:
                            db.add(EtfFundSnapshot(**vals))
                        count += 1

                # 范围模式加间隔，避免限频
                if total_days > 1:
                    time.sleep(0.5)

            except Exception as day_err:
                log.warning("etf_nav_day_err", date=td_str,
                            error=str(day_err)[:80])
                continue

        log.info("sync_etf_nav_share_done",
                 count=count, days=total_days,
                 seconds=round(time.time() - t0, 1))

        # 覆盖率校验：日常模式下数据源异常 → 降级为 failed，阻止水位推进
        if total_days == 1 and len(etf_codes) > 0:
            coverage = count / len(etf_codes)
            if coverage < 0.5:
                error_msg = (f"覆盖率过低 {count}/{len(etf_codes)}"
                             f" ({coverage:.0%})，疑似数据源异常")
                log.warning("sync_etf_nav_share_low_coverage",
                            count=count, expected=len(etf_codes),
                            coverage=f"{coverage:.0%}")
            elif share_failed:
                error_msg = "份额数据拉取失败，水位不推进"
                log.warning("sync_etf_nav_share_no_share",
                            nav_count=count)

    except Exception as e:
        error_msg = str(e)
        log.error("sync_etf_nav_share_failed", error=error_msg)
    finally:
        if task_id:
            from utils.task_store import TaskStatus
            st = TaskStatus.COMPLETED if not error_msg else TaskStatus.FAILED
            msg = (f"ETF 净值+份额快照同步完成 ({count} 条)"
                   if not error_msg else f"失败: {error_msg}")
            _update_task(task_id, st,
                         result={"progress": 100, "message": msg, "count": count})
        write_watermark(
            data_type="etf_nav_share", mode="all",
            last_sync_date=trade_date_str,
            t_start=t0,
            status="success" if not error_msg else "failed",
            error_msg=error_msg,
        )

    return {"rows": count}


def _get_trade_dates_for_range(start: str, end: str) -> list[str]:
    """获取 start~end 之间的 A 股交易日列表"""
    try:
        from data_sources.tushare_source import TushareSource
        import data_sources.tushare_source as tushare_module
        ts = TushareSource()

        @tushare_module.with_tushare_retry(max_retries=2, delay=1.0)
        def _call():
            return ts.pro.trade_cal(
                start_date=start, end_date=end, is_open="1"
            )

        df = _call()
        if df is not None and not df.empty:
            return sorted(df["cal_date"].tolist())
    except Exception as e:
        log.warning("trade_cal_failed", error=str(e)[:80])

    # fallback: 简单日期序列（跳周末）
    import pandas as pd
    rng = pd.bdate_range(start=start, end=end, freq="B")
    return [d.strftime("%Y%m%d") for d in rng]

