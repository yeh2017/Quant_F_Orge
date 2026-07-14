"""
可转债数据同步模块
==================
从 data_sync_service.py 拆分出来的可转债同步逻辑。
包含：基本信息、历史行情、因子快照 三个同步方法。
"""

import time
import structlog
from datetime import date, datetime, timedelta
from typing import Optional

from core.database import db_session
from jobs.sync_base import write_watermark

log = structlog.get_logger("sync_bond")


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


def sync_bond_basic(task_id: Optional[str] = None):
    """
    同步可转债基本信息到本地 ConvertibleBondBasic 表。
    数据来源：Tushare Pro cb_basic（在市可转债）
    """
    from models.quant_data import ConvertibleBondBasic

    log.info("sync_bond_basic_start")
    t0 = time.time()
    count = 0
    error_msg = None

    _update_task(task_id, 0, message="正在从 Tushare (cb_basic) 拉取在市可转债列表...")

    try:
        from data_sources.tushare_source import TushareSource
        ts = TushareSource()
        ts_list = ts.get_cb_basic()

        if not ts_list:
            log.warning("sync_bond_basic_ts_empty",
                        hint="Tushare cb_basic 返回空，降级到 AkShare 回补 underlying 字段")
            # 降级：AkShare bond_zh_cov 拿 underlying_name/underlying_code 回补已有记录
            try:
                from data_sources.akshare_bond_source import get_cb_premium_list
                ak_list = get_cb_premium_list()
                if ak_list:
                    ak_map = {str(r.get("code", "")).strip(): r for r in ak_list if r.get("code")}
                    # 安全阈值：AkShare 返回过少时不执行退市标记，防止不完整数据误标
                    safe_to_delist = len(ak_map) >= 500
                    patched = 0
                    delisted = 0
                    with db_session() as db:
                        from models.quant_data import ConvertibleBondBasic
                        for rec in db.query(ConvertibleBondBasic).filter_by(listed=True).all():
                            ak = ak_map.get(rec.code)
                            if not ak:
                                # AkShare 名单中没有 → 仅在数据量安全时标记退市
                                if safe_to_delist:
                                    rec.listed = False
                                    delisted += 1
                                continue
                            changed = False
                            if not rec.underlying_name and ak.get("underlying_name"):
                                rec.underlying_name = str(ak["underlying_name"]).strip()
                                changed = True
                            if not rec.underlying_code and ak.get("underlying_code"):
                                rec.underlying_code = str(ak["underlying_code"]).strip()
                                changed = True
                            if not rec.rating and ak.get("rating"):
                                rec.rating = str(ak["rating"]).strip()
                                changed = True
                            if not rec.issue_date and ak.get("list_date"):
                                try:
                                    raw = str(ak["list_date"]).replace("-", "")[:8]
                                    rec.issue_date = date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
                                    changed = True
                                except (ValueError, TypeError):
                                    log.debug("fallback_issue_date_parse_error", code=rec.code)
                            if changed:
                                patched += 1
                    log.info("sync_bond_basic_akshare_fallback",
                             patched=patched, delisted=delisted)
                    _update_task(task_id, 100,
                                 message=f"Tushare 不可用，AkShare 回补 {patched} 条 underlying 字段")
                else:
                    _update_task(task_id, 0, message="Tushare 和 AkShare 均无数据")
            except Exception as ak_err:
                log.warning("sync_bond_basic_akshare_fallback_failed", error=str(ak_err))
                _update_task(task_id, 0, message=f"AkShare 降级也失败: {ak_err}")
            return

        log.info("sync_bond_basic_fetched", source="tushare", rows=len(ts_list))
        _update_task(task_id, 50,
                     message=f"已拉取 {len(ts_list)} 只在市可转债，正在写入数据库...")

        def _parse_date(v):
            try:
                if not v or str(v) in ("nan", "", "None"):
                    return None
                s = str(v).replace("-", "")[:8]
                return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
            except (ValueError, TypeError):
                return None

        new_codes = set()
        with db_session() as db:
            for item in ts_list:
                try:
                    ts_code = str(item.get("ts_code", "")).strip()
                    code = ts_code.replace(".SH", "").replace(".SZ", "").strip()
                    if not code:
                        continue
                    new_codes.add(code)

                    existing = db.query(ConvertibleBondBasic).filter(
                        ConvertibleBondBasic.code == code
                    ).first()

                    mature_dt = _parse_date(
                        item.get("mature_date") or item.get("maturity_date")
                    )
                    # delist_date 有值且 ≤ 今天 → 已退市/赎回
                    # delist_date 为未来日期 → 已公告但尚未退市，仍视为在市
                    delist_dt = _parse_date(item.get("delist_date"))
                    issue_dt = _parse_date(
                        item.get("issue_date") or item.get("list_date")
                    )
                    today = date.today()
                    is_listed = delist_dt is None or delist_dt > today
                    if is_listed and mature_dt and mature_dt <= today:
                        is_listed = False
                    # 未上市新债：issue_date 为空或为未来日期 → 尚未交易
                    if is_listed and (issue_dt is None or issue_dt > today):
                        is_listed = False

                    data = {
                        "code": code,
                        "name": str(item.get("name") or item.get("bond_short_name") or "").strip() or None,
                        "underlying_code": str(item.get("underlying_code") or "").strip() or None,
                        "underlying_name": str(item.get("underlying_name") or "").strip() or None,
                        "rating": str(item.get("rating") or "").strip() or None,
                        "issue_date": _parse_date(
                            item.get("issue_date") or item.get("list_date")
                        ),
                        "mature_date": mature_dt,
                        "face_value": float(item.get("face_value") or item.get("par_value") or 100),
                        "convert_price": float(item.get("convert_price") or 0) or None,
                        "listed": is_listed,
                    }

                    if existing:
                        for k, v in data.items():
                            setattr(existing, k, v)
                    else:
                        db.add(ConvertibleBondBasic(**data))
                    count += 1
                except Exception as row_err:
                    log.warning("sync_bond_basic_row_err", error=str(row_err))

            # 将不在 Tushare 列表中的旧记录标记为退市
            old_records = db.query(ConvertibleBondBasic).filter(
                ConvertibleBondBasic.listed == True  # noqa: E712
            ).all()
            deactivated = 0
            for r in old_records:
                if r.code not in new_codes:
                    r.listed = False
                    deactivated += 1
            if deactivated:
                log.info("sync_bond_basic_deactivated", count=deactivated)

            # ── AkShare 字段级回补：rating / issue_date 缺失时补全 ──
            null_rating = db.query(ConvertibleBondBasic).filter(
                ConvertibleBondBasic.listed == True,  # noqa: E712
                ConvertibleBondBasic.rating == None,
            ).count()
            null_issue = db.query(ConvertibleBondBasic).filter(
                ConvertibleBondBasic.listed == True,  # noqa: E712
                ConvertibleBondBasic.issue_date == None,
            ).count()

            if null_rating > 0 or null_issue > 0:
                log.info("bond_basic_field_backfill_start",
                         null_rating=null_rating, null_issue=null_issue)
                try:
                    from data_sources.akshare_bond_source import get_cb_premium_list
                    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FTE
                    with ThreadPoolExecutor(max_workers=1) as ex:
                        future = ex.submit(get_cb_premium_list)
                        ak_list = future.result(timeout=30)
                    ak_map = {str(r.get("code", "")).strip(): r for r in ak_list if r.get("code")}
                    patched_rating = 0
                    patched_issue = 0
                    for rec in db.query(ConvertibleBondBasic).filter_by(listed=True).all():
                        ak = ak_map.get(rec.code)
                        if not ak:
                            continue
                        if not rec.rating and ak.get("rating"):
                            rec.rating = str(ak["rating"]).strip()
                            patched_rating += 1
                        if not rec.issue_date and ak.get("list_date"):
                            try:
                                raw = str(ak["list_date"]).replace("-", "")[:8]
                                rec.issue_date = date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
                                patched_issue += 1
                            except (ValueError, TypeError):
                                log.debug("backfill_issue_date_parse_error", code=rec.code)
                    log.info("bond_basic_field_backfill_done",
                             patched_rating=patched_rating, patched_issue=patched_issue)
                except (FTE, Exception) as ak_err:
                    log.warning("bond_basic_field_backfill_failed", error=str(ak_err)[:80])

        log.info("sync_bond_basic_done", count=count,
                 seconds=round(time.time() - t0, 1))

    except Exception as e:
        error_msg = str(e)
        log.error("sync_bond_basic_failed", error=error_msg)
    finally:
        if task_id:
            from utils.task_store import TaskStatus
            st = TaskStatus.COMPLETED if not error_msg else TaskStatus.FAILED
            msg = (f"可转债基本信息同步完成 ✅ ({count} 只)"
                   if not error_msg else f"同步失败: {error_msg}")
            _update_task(task_id, st, result={"message": msg, "count": count})
        write_watermark(
            data_type="bond_basic", mode="all",
            last_sync_date=str(date.today()), t_start=t0,
            status="success" if not error_msg else "failed",
            error_msg=error_msg,
        )


def sync_bond_history(start_date: Optional[str] = None, end_date: Optional[str] = None,
                      task_id: Optional[str] = None, force_refill: bool = False):
    """
    同步可转债历史行情到 ConvertibleBondBar 表。
    带水位增量：从 DB 最新日期+1 开始，避免重复遍历。
    """
    import pandas as pd

    if not end_date:
        from utils.trade_date import resolve_end_date
        end_date = resolve_end_date(fmt="%Y%m%d")
    if not start_date:
        start_date = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=730)).strftime("%Y%m%d")
        log.warning("bond_history_no_start_date", fallback=start_date)

    log.info("sync_bond_history_start", start=start_date, end=end_date)
    t0 = time.time()
    total_count = 0
    error_msg = None

    def _rpt(cur, total, msg):
        if task_id:
            pct = round(cur / total * 100) if total > 0 else 0
            _update_task(task_id, pct, message=msg)

    try:
        from data_sources.tushare_source import TushareSource
        ts = TushareSource()

        # ── 水位增量（force_refill 时跳过）──
        actual_start = start_date
        if force_refill:
            log.info("bond_history_force_refill", start_date=start_date)
        else:
            from jobs.sync_base import calc_next_start
            actual_start = calc_next_start("bond_history", "all", start_date)

        if actual_start > end_date:
            log.info("bond_history_already_up_to_date",
                     start=actual_start, end=end_date)
            if task_id:
                from utils.task_store import task_store, TaskStatus
                task_store.update_task(task_id, TaskStatus.COMPLETED,
                                      result={"progress": 100,
                                              "message": "可转债行情已是最新",
                                              "count": 0})
            return

        # 使用 Tushare trade_cal 获取真实 A 股交易日（跳过节假日）
        import data_sources.tushare_source as tushare_module

        @tushare_module.with_tushare_retry(max_retries=2, delay=1.0)
        def _fetch_trade_cal():
            return ts.pro.trade_cal(
                start_date=actual_start, end_date=end_date, is_open="1"
            )

        df_cal = _fetch_trade_cal()
        if df_cal is not None and not df_cal.empty:
            trade_dates = sorted(df_cal["cal_date"].tolist())
        else:
            # fallback: bdate_range 仅跳周末（节假日可能空转）
            date_range = pd.bdate_range(start=actual_start, end=end_date, freq="B")
            trade_dates = [d.strftime("%Y%m%d") for d in date_range]
        total_days = len(trade_dates)
        log.info("sync_bond_history_date_range", days=total_days,
                 start=actual_start, end=end_date)
        _rpt(0, total_days, f"开始按交易日同步 {total_days} 天的可转债行情...")

        for day_idx, trade_date_str in enumerate(trade_dates, 1):
            try:
                daily_list = ts.get_cb_daily(trade_date_str)
                if not daily_list:
                    if day_idx == 1:
                        _rpt(0, total_days,
                             "⚠️ cb_daily 首日返回空（非交易日或积分不足），继续尝试...")
                        log.warning("sync_bond_history_empty",
                                    trade_date=trade_date_str,
                                    hint="cb_daily 返回空（非交易日或积分不足）")
                    continue

                with db_session() as db:
                    trade_dt = date(int(trade_date_str[:4]),
                                   int(trade_date_str[4:6]),
                                   int(trade_date_str[6:8]))
                    # upsert：覆盖已有记录（修复历史脏数据如 vol/amount=None）
                    from sqlalchemy import text as sa_text
                    upsert_sql = sa_text("""
                        INSERT INTO convertible_bond_bar
                            (code, trade_date, open, high, low, close, volume, turnover)
                        VALUES (:code, :td, :open, :high, :low, :close, :vol, :turnover)
                        ON CONFLICT(code, trade_date) DO UPDATE SET
                            open=excluded.open, high=excluded.high,
                            low=excluded.low, close=excluded.close,
                            volume=excluded.volume, turnover=excluded.turnover
                    """)
                    for item in daily_list:
                        code = str(item.get("code", "")).strip()
                        if not code:
                            continue
                        db.execute(upsert_sql, {
                            "code": code, "td": trade_dt,
                            "open": item.get("open"), "high": item.get("high"),
                            "low": item.get("low"), "close": item.get("close"),
                            "vol": item.get("volume"), "turnover": item.get("amount"),
                        })
                        total_count += 1

                if day_idx % 10 == 0 or day_idx == total_days:
                    _rpt(day_idx, total_days,
                         f"行情 {day_idx}/{total_days} 天，已写 {total_count} 条")
                from settings import BOND_FETCH_SLEEP
                time.sleep(BOND_FETCH_SLEEP)

            except Exception as day_err:
                log.warning("sync_bond_history_day_err",
                            trade_date=trade_date_str, error=str(day_err))
                continue

        log.info("sync_bond_history_done",
                 count=total_count, seconds=round(time.time() - t0, 1))

    except Exception as e:
        error_msg = str(e)
        log.error("sync_bond_history_failed", error=error_msg)
    finally:
        if task_id:
            from utils.task_store import TaskStatus
            st = TaskStatus.COMPLETED if not error_msg else TaskStatus.FAILED
            msg = (f"可转债 OHLCV 同步完成 ✅ (共 {total_count} 条记录)"
                   if not error_msg else f"失败: {error_msg}")
            _update_task(task_id, st,
                         result={"progress": 100, "message": msg,
                                 "count": total_count})
        # 取 DB 实际最新日期作为水位（与 bars/etf 统一）
        try:
            from sqlalchemy import text as sa_text
            with db_session() as _db:
                _r = _db.execute(sa_text(
                    "SELECT MAX(trade_date) FROM convertible_bond_bar"
                )).fetchone()
                actual_max = str(_r[0]).replace("-", "")[:8] if _r and _r[0] else end_date
        except Exception:
            actual_max = end_date
        write_watermark(
            data_type="bond_history", mode="all",
            last_sync_date=actual_max, t_start=t0,
            status="success" if (not error_msg and total_count > 0) else
                   "empty" if (not error_msg and total_count == 0) else "failed",
            error_msg=error_msg,
        )


def sync_bond_factor(trade_date: Optional[str] = None, task_id: Optional[str] = None):
    """
    同步可转债因子快照到 ConvertibleBondFactor 表。
    core 计算: double_low_score = close_price + premium_ratio (越小越好)
    """
    from models.quant_data import (
        ConvertibleBondBasic, ConvertibleBondFactor,
        StockDailyBar, StockDailyFactor, StockFinancial,
    )
    from data_sources.akshare_bond_source import get_cb_premium_list

    if not trade_date:
        # 对齐行情表水位，避免因子日期超前于行情（AkShare 实时数据可能包含盘中今日数据）
        from utils.trade_date import get_table_latest_date
        bar_latest = get_table_latest_date("bond_bar")
        if bar_latest:
            trade_date = bar_latest.replace("-", "")
        else:
            from utils.trade_date import resolve_end_date
            trade_date = resolve_end_date(fmt="%Y%m%d")
    trade_dt = datetime.strptime(trade_date, "%Y%m%d").date()

    log.info("sync_bond_factor_start", trade_date=trade_date)
    t0 = time.time()
    count = 0
    error_msg = None

    # 水位去重由外层 data_sync_service._should_skip("bond_history") 控制（24h 间隔），
    # 此处不再做内部跳过，确保每次调用都能用最新 Bar 数据刷新因子表。

    _update_task(task_id, 0,
                 message=f"Step 1/4: 正在从本地读取可转债基本信息...")

    try:
        from data_sources.tushare_source import TushareSource
        ts = TushareSource()

        # Step 1: 直接从本地 ConvertibleBondBasic 表读取（单一数据源，不重复调用 Tushare）
        with db_session() as db:
            rows = db.query(ConvertibleBondBasic).filter_by(listed=True).all()
            basic_map = {
                r.code: {
                    "code": r.code, "name": r.name,
                    "underlying_code": r.underlying_code,
                    "convert_price": r.convert_price,
                    "rating": r.rating,
                    "mature_date": r.mature_date,
                }
                for r in rows
            }

        if not basic_map:
            log.warning("sync_bond_factor_no_basic_data")
            return

        # 清理退市/未上市债的因子残留（防止脏数据累积）
        # 安全阈值：正常应有 300+ 只在市债，低于 100 说明数据源异常，跳过清理
        listed_codes = set(basic_map.keys())
        if len(listed_codes) >= 100:
            with db_session() as db:
                orphan_deleted = db.query(ConvertibleBondFactor).filter(
                    ~ConvertibleBondFactor.code.in_(listed_codes)
                ).delete(synchronize_session=False)
                if orphan_deleted:
                    log.info("bond_factor_orphan_cleanup", deleted=orphan_deleted)
        else:
            log.warning("bond_factor_cleanup_skipped",
                        listed_count=len(listed_codes),
                        reason="listed count too low, possible data source issue")


        # Step 2: 行情数据（优先本地 bar 表，fallback Tushare cb_daily）
        _update_task(task_id, 25,
                     message=f"Step 2/4: 读取可转债行情 (本地 bar 表 → Tushare cb_daily)...")
        daily_map = {}

        # 2a: 从本地 ConvertibleBondBar 表读取（仅查精确目标日期，不 fallback 旧日期）
        try:
            from models.quant_data import ConvertibleBondBar
            with db_session() as db:
                bar_rows = db.query(ConvertibleBondBar).filter(
                    ConvertibleBondBar.trade_date == trade_dt
                ).all()
                if bar_rows:
                    log.info("bond_factor_bar_from_local", date=str(trade_dt),
                             count=len(bar_rows))
                    for r in bar_rows:
                        daily_map[r.code] = {
                            "code": r.code,
                            "close": float(r.close) if r.close is not None else None,
                            "open": float(r.open) if r.open is not None else None,
                            "high": float(r.high) if r.high is not None else None,
                            "low": float(r.low) if r.low is not None else None,
                            "volume": float(r.volume) if r.volume is not None else None,
                            "amount": float(r.turnover) if r.turnover is not None else None,
                        }
        except Exception as bar_err:
            log.warning("bond_factor_local_bar_failed", error=str(bar_err))

        # 2b: Tushare cb_daily 补充（5000积分够用）
        #     - 本地 Bar 未覆盖的可转债：整条写入
        #     - 已有条目：合并 Tushare 独有字段（pure_bond_value 等本地 bar 表不含的字段）
        try:
            ts_daily_list = ts.get_cb_daily(trade_date)
            supplemented = 0
            merged = 0
            _TS_ONLY_FIELDS = ("pure_bond_value",)  # 本地 bar 表没有、仅 Tushare 有的字段
            for d in ts_daily_list:
                code = d.get("code", "")
                if not code:
                    continue
                if code not in daily_map:
                    daily_map[code] = d
                    supplemented += 1
                else:
                    # 合并 Tushare 独有字段到已有条目
                    for fld in _TS_ONLY_FIELDS:
                        if d.get(fld) is not None and daily_map[code].get(fld) is None:
                            daily_map[code][fld] = d[fld]
                            merged += 1
            if supplemented or merged:
                log.info("bond_factor_tushare_supplement",
                         count=supplemented, merged=merged, total=len(daily_map))
        except Exception as ts_err:
            log.warning("bond_factor_tushare_daily_failed", error=str(ts_err)[:80])

        # Step 3: 溢价率（本地计算：溢价率 = 收盘价 / 转股价值 - 1）
        _update_task(task_id, 50,
                     message="Step 3/4: 计算溢价率 (本地计算 + AkShare 增强)...")
        ak_premium_map = {}

        # 3a: AkShare 溢价率（可选增强，超时不阻塞）
        try:
            from data_sources.akshare_bond_source import get_cb_premium_list
            # Windows 不支持 signal.alarm，用 ThreadPoolExecutor 超时
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FTE
            with ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(get_cb_premium_list)
                ak_premium_list = future.result(timeout=30)
            ak_premium_map = {p["code"]: p for p in ak_premium_list if p.get("code")}
            log.info("akshare_premium_ok", count=len(ak_premium_map))
        except (FTE, Exception) as ak_err:
            log.warning("akshare_premium_skipped", error=str(ak_err)[:80],
                        hint="使用本地数据计算溢价率")

        # Step 4: 批量预查正股行情（一次查完，避免逐只开 session）
        underlying_codes = set()
        for code in set(basic_map.keys()) | set(daily_map.keys()):
            uc = basic_map.get(code, {}).get("underlying_code") or ""
            # 支持裸码（6位）和带后缀码（000002.SZ）
            if "." in uc:
                underlying_codes.add(uc)
            elif uc and len(uc) == 6:
                uc = f"{uc}.SH" if uc[:2] in ("60", "68") else f"{uc}.SZ"
                underlying_codes.add(uc)

        underlying_data = {}  # { code: (close, pe, roe) }
        if underlying_codes:
            from sqlalchemy import func as sqlfunc
            with db_session() as db:
                # 最新收盘价
                bar_sub = db.query(
                    StockDailyBar.code,
                    sqlfunc.max(StockDailyBar.trade_date).label("max_date")
                ).filter(StockDailyBar.code.in_(underlying_codes)
                ).group_by(StockDailyBar.code).subquery()

                bar_rows = db.query(StockDailyBar.code, StockDailyBar.close).join(
                    bar_sub, (StockDailyBar.code == bar_sub.c.code) &
                             (StockDailyBar.trade_date == bar_sub.c.max_date)
                ).all()
                close_map = {r[0]: float(r[1]) if r[1] else None for r in bar_rows}

                # 最新 PE
                fac_sub = db.query(
                    StockDailyFactor.code,
                    sqlfunc.max(StockDailyFactor.trade_date).label("max_date")
                ).filter(StockDailyFactor.code.in_(underlying_codes)
                ).group_by(StockDailyFactor.code).subquery()

                fac_rows = db.query(StockDailyFactor.code, StockDailyFactor.pe_ttm).join(
                    fac_sub, (StockDailyFactor.code == fac_sub.c.code) &
                             (StockDailyFactor.trade_date == fac_sub.c.max_date)
                ).all()
                pe_map = {r[0]: float(r[1]) if r[1] else None for r in fac_rows}

                # 最新 ROE
                fin_sub = db.query(
                    StockFinancial.code,
                    sqlfunc.max(StockFinancial.report_date).label("max_date")
                ).filter(StockFinancial.code.in_(underlying_codes)
                ).group_by(StockFinancial.code).subquery()

                fin_rows = db.query(StockFinancial.code, StockFinancial.roe).join(
                    fin_sub, (StockFinancial.code == fin_sub.c.code) &
                             (StockFinancial.report_date == fin_sub.c.max_date)
                ).all()
                roe_map = {r[0]: float(r[1]) if r[1] else None for r in fin_rows}

                for uc in underlying_codes:
                    underlying_data[uc] = (close_map.get(uc), pe_map.get(uc), roe_map.get(uc))

        # Step 5: 合并、计算、upsert
        all_codes = set(basic_map.keys()) | set(daily_map.keys())
        _update_task(task_id, 75,
                     message=f"Step 4/4: 计算因子并写入数据库 ({len(all_codes)} 只可转债)...")

        # 预加载前一日因子表 close_price（carry-forward：无交易债价格不变）
        prev_close_map: dict[str, float] = {}
        from sqlalchemy import func as sqlfunc2
        with db_session() as _db:
            prev_dt = _db.query(sqlfunc2.max(ConvertibleBondFactor.trade_date)).filter(
                ConvertibleBondFactor.trade_date < trade_dt
            ).scalar()
            if prev_dt:
                prev_rows = _db.query(
                    ConvertibleBondFactor.code, ConvertibleBondFactor.close_price
                ).filter(
                    ConvertibleBondFactor.trade_date == prev_dt,
                    ConvertibleBondFactor.close_price.is_not(None),
                ).all()
                prev_close_map = {r[0]: float(r[1]) for r in prev_rows}
                log.info("prev_close_loaded", count=len(prev_close_map),
                         prev_date=str(prev_dt))

        with db_session() as db:
            for code in all_codes:
                try:
                    basic = basic_map.get(code, {})
                    daily = daily_map.get(code, {})
                    ak_p = ak_premium_map.get(code, {})

                    # 收盘价优先级：Bar/Tushare > AkShare > 前日因子表(carry-forward)
                    close_price = (daily.get("close")
                                   or ak_p.get("close")
                                   or prev_close_map.get(code))
                    if not close_price:
                        continue

                    premium_ratio = ak_p.get("premium_ratio")
                    pure_bond_value = (ak_p.get("pure_bond_value")
                                       or daily.get("pure_bond_value"))
                    pure_bond_premium = ak_p.get("pure_bond_premium")
                    convert_value = ak_p.get("convert_value")
                    remaining_size = ak_p.get("remaining_size")  # 仅取 AkShare，不 fallback 成交额

                    # 本地计算溢价率（AkShare 无数据时的 fallback）
                    # 转股价值 = 100 / 转股价 × 正股收盘价
                    # 溢价率 = (转债价 / 转股价值 - 1) × 100
                    if premium_ratio is None:
                        cp = float(basic.get("convert_price") or 0)
                        uc = basic.get("underlying_code") or ""
                        if "." in uc:
                            uc_full = uc
                        elif uc and len(uc) == 6:
                            uc_full = f"{uc}.SH" if uc[:2] in ("60", "68") else f"{uc}.SZ"
                        else:
                            uc_full = uc
                        stk_close = underlying_data.get(uc_full, (None, None, None))[0] if uc_full else None
                        if cp > 0 and stk_close and stk_close > 0:
                            convert_value_calc = 100.0 / cp * stk_close
                            premium_ratio = round(
                                (float(close_price) / convert_value_calc - 1) * 100, 2)
                            if convert_value is None:
                                convert_value = round(convert_value_calc, 2)

                    double_low_score = None
                    if close_price and premium_ratio is not None:
                        double_low_score = round(
                            float(close_price) + float(premium_ratio), 2)

                    underlying_code = basic.get("underlying_code") or ""
                    if "." not in underlying_code and underlying_code and len(underlying_code) == 6:
                        prefix = underlying_code[:2]
                        if prefix in ("60", "68"):
                            underlying_code = f"{underlying_code}.SH"
                        else:
                            underlying_code = f"{underlying_code}.SZ"

                    underlying_close, underlying_pe, underlying_roe = (
                        underlying_data.get(underlying_code, (None, None, None)))

                    mature_date = basic.get("mature_date")

                    existing_rec = db.query(ConvertibleBondFactor).filter_by(
                        code=code, trade_date=trade_dt
                    ).first()

                    # 评级清洗：去除 Tushare 偶尔附加的 'sti' 后缀
                    raw_rating = basic.get("rating") or ak_p.get("rating") or None
                    if raw_rating and isinstance(raw_rating, str):
                        raw_rating = raw_rating.replace("sti", "").strip() or None

                    vals = dict(
                        code=code,
                        name=basic.get("name") or ak_p.get("name"),
                        trade_date=trade_dt,
                        close_price=float(close_price) if close_price else None,
                        remaining_size=float(remaining_size) if remaining_size else None,
                        premium_ratio=float(premium_ratio) if premium_ratio is not None else None,
                        pure_bond_value=float(pure_bond_value) if pure_bond_value else None,
                        pure_bond_premium=float(pure_bond_premium) if pure_bond_premium is not None else None,
                        convert_value=float(convert_value) if convert_value else None,
                        underlying_code=underlying_code or None,
                        underlying_close=underlying_close,
                        underlying_pe=underlying_pe,
                        underlying_roe=underlying_roe,
                        convert_price=float(basic.get("convert_price") or ak_p.get("convert_price") or 0) or None,
                        rating=raw_rating,
                        mature_date=mature_date,
                        double_low_score=double_low_score,
                    )

                    # 因子表只存可分析记录：无双低分（无溢价率数据）的债不写入
                    if double_low_score is None:
                        if existing_rec:
                            db.delete(existing_rec)
                        continue

                    if existing_rec:
                        for k, v in vals.items():
                            setattr(existing_rec, k, v)
                    else:
                        db.add(ConvertibleBondFactor(**vals))
                    count += 1

                except Exception as row_e:
                    log.warning("sync_bond_factor_row_err",
                                code=code, error=str(row_e))

        log.info("sync_bond_factor_done",
                 count=count, seconds=round(time.time() - t0, 1))

    except Exception as e:
        error_msg = str(e)
        log.error("sync_bond_factor_failed", error=error_msg)
    finally:
        if task_id:
            from utils.task_store import TaskStatus
            st = TaskStatus.COMPLETED if not error_msg else TaskStatus.FAILED
            msg = (f"可转债因子计算完成 ✅ ({count} 只)"
                   if not error_msg else f"失败: {error_msg}")
            _update_task(task_id, st,
                         result={"progress": 100, "message": msg, "count": count})
        write_watermark(
            data_type="bond_factor", mode="all",
            last_sync_date=trade_date, t_start=t0,
            status="success" if not error_msg else "failed",
            error_msg=error_msg,
        )
