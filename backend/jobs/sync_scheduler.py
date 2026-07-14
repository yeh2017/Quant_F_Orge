"""
同步调度器
=========
编排 Tushare 批量拉取 → Baostock/AkShare fallback 的两阶段流程。
- 网络 IO 并发（线程池）
- DB 写入单线程批量
"""

import time
import threading
import structlog
import pandas as pd
from typing import List, Set, Optional, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.database import db_session
from data_sources.tushare_source import TushareSource
from jobs.writers import BarWriter, FactorWriter

log = structlog.get_logger("sync_scheduler")


class SyncScheduler:
    """批量 + fallback 两阶段同步调度"""

    def __init__(self, ts_source: TushareSource, bar_writer: BarWriter, factor_writer: FactorWriter):
        self._ts = ts_source
        self._bar_w = bar_writer
        self._factor_w = factor_writer

    # ================================================================
    #  对外入口
    # ================================================================

    def run(
        self,
        need_sync: List[str],
        batch_start: str,
        end_date: str,
        start_date: str,
        incremental_starts: Dict,
        task_id: Optional[str] = None,
        total_codes: int = 0,
        already_done: int = 0,
    ) -> dict:
        """
        执行两阶段同步。
        Returns:
            {"synced": int, "failed": int, "failed_codes": [str],
             "no_trade": int, "no_trade_codes": [str]}
        """
        # Phase A: Tushare 按交易日批量
        batch_synced = self._batch_phase(need_sync, batch_start, end_date, task_id)

        # Phase B: 未覆盖的 fallback
        remaining = [c for c in need_sync if c not in batch_synced]
        failed_codes = []
        no_trade_codes = []

        if remaining:
            failed_codes, no_trade_codes = self._fallback_phase(
                remaining, start_date, end_date, incremental_starts,
                task_id, total_codes, already_done + len(batch_synced),
            )
        else:
            log.info("batch_covers_all", count=len(batch_synced))

        return {
            "synced": len(batch_synced) + len(remaining) - len(failed_codes) - len(no_trade_codes),
            "failed": len(failed_codes),
            "failed_codes": failed_codes[:20],
            "no_trade": len(no_trade_codes),
            "no_trade_codes": no_trade_codes[:10],
        }

    # ================================================================
    #  Phase A: Tushare 批量
    # ================================================================

    def _batch_phase(self, target_codes: List[str], start_date: str, end_date: str,
                     task_id: Optional[str]) -> Set[str]:
        trade_dates = self._get_trade_dates(start_date, end_date)
        if not trade_dates:
            log.warning("no_trade_dates", start=start_date, end=end_date)
            return set()

        target_set = set(target_codes)
        synced: Set[str] = set()
        total_dates = len(trade_dates)
        log.info("batch_start", trade_dates=total_dates, targets=len(target_codes))

        import data_sources.tushare_source as tushare_module

        for i, td in enumerate(trade_dates):
            try:
                # 拉取全市场行情
                @tushare_module.with_tushare_retry(max_retries=2, delay=1.0)
                def _fetch_daily():
                    return self._ts.pro.daily(trade_date=td)

                @tushare_module.with_tushare_retry(max_retries=2, delay=1.0)
                def _fetch_adj():
                    return self._ts.pro.adj_factor(trade_date=td, fields="ts_code,adj_factor")

                df_daily = _fetch_daily()

                # daily_basic 需要 2000 积分，隔离 try-catch 避免影响日线行情写入
                df_basic = None
                try:
                    @tushare_module.with_tushare_retry(max_retries=2, delay=1.0)
                    def _fetch_basic():
                        return self._ts.pro.daily_basic(
                            trade_date=td,
                            fields="ts_code,trade_date,turnover_rate,volume_ratio,pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,total_mv,circ_mv"
                        )
                    df_basic = _fetch_basic()

                    # 字段完整性校验（防静默丢失）
                    from data_sources.tushare_source import validate_tushare_fields
                    validate_tushare_fields(df_basic,
                        ["turnover_rate", "pe_ttm", "pb", "total_mv", "circ_mv"],
                        api_name="daily_basic")
                except Exception as e:
                    log.warning("daily_basic_fetch_failed", trade_date=td, error=str(e)[:80])

                # 单独拉复权因子并合并
                adj_map = None
                try:
                    df_adj = _fetch_adj()
                    if df_adj is not None and not df_adj.empty:
                        adj_map = df_adj.set_index("ts_code")["adj_factor"].to_dict()
                        if df_basic is not None and not df_basic.empty:
                            df_basic["adj_factor"] = df_basic["ts_code"].map(adj_map)
                except Exception as e:
                    log.warning("adj_factor_fetch_failed", trade_date=td, error=str(e))

                # 将 adj_factor 合并到 daily 行情，一起写入 bars 表
                # 优先从 df_basic 中转（含 PE/PB 等因子场景），df_basic 为 None 时直接用 adj_map
                if df_daily is not None and not df_daily.empty:
                    if (df_basic is not None and not df_basic.empty
                            and "adj_factor" in df_basic.columns):
                        adj_from_basic = df_basic.set_index("ts_code")["adj_factor"].to_dict()
                        df_daily["adj_factor"] = df_daily["ts_code"].map(adj_from_basic)
                    elif adj_map:
                        df_daily["adj_factor"] = df_daily["ts_code"].map(adj_map)

                trade_date_obj = pd.to_datetime(td, format="%Y%m%d").date()

                with db_session() as db:
                    new_synced = self._bar_w.upsert_batch(db, df_daily, trade_date_obj, target_set)
                    synced |= new_synced
                    if df_basic is not None and not df_basic.empty:
                        self._factor_w.upsert_batch(db, df_basic, trade_date_obj, target_set)

                if task_id:
                    self._report(task_id, i + 1, total_dates, f"批量拉取: {td}")

                from settings import TUSHARE_FETCH_SLEEP
                time.sleep(TUSHARE_FETCH_SLEEP)

            except Exception as e:
                log.error("batch_fetch_failed", trade_date=td, error=str(e))
                continue

        log.info("batch_done", synced=len(synced), total=len(target_codes))
        return synced

    # ================================================================
    #  Phase B: Fallback 逐只拉取
    # ================================================================

    def _fallback_phase(
        self,
        remaining: List[str],
        start_date: str,
        end_date: str,
        incremental_starts: Dict,
        task_id: Optional[str],
        total_codes: int,
        already_done: int,
    ) -> tuple[List[str], List[str]]:
        """
        逐只拉取未覆盖的股票。
        Returns: (error_codes, no_trade_codes)
            error_codes: API 异常导致的真正失败
            no_trade_codes: 三个数据源均无数据（停牌/未交易）
        """
        log.info("fallback_start", count=len(remaining))
        error_codes = []
        no_trade_codes = []

        # AkShare 立即初始化（HTTP 无状态，几乎不会失败）
        # BaoStock 懒加载 + 线程安全：只有前两个源都失败时才尝试连接
        _bs_lock = threading.Lock()
        _bs_cache = [None, False]  # [instance, initialized]
        def _get_bs():
            if not _bs_cache[1]:
                with _bs_lock:
                    if not _bs_cache[1]:  # double-check
                        _bs_cache[0] = self._init_baostock()
                        _bs_cache[1] = True
            return _bs_cache[0]
        ak_source = self._init_akshare()

        completed_count = already_done

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_to_code = {}
            for code in remaining:
                short_code = code.split(".")[0] if "." in code else code
                effective_start = incremental_starts.get(code) or start_date
                future = executor.submit(
                    self._fetch_single,
                    code, short_code, effective_start, end_date,
                    _get_bs, ak_source,
                )
                future_to_code[future] = code

            for future in as_completed(future_to_code):
                code = future_to_code[future]
                completed_count += 1
                effective_start = incremental_starts.get(code) or start_date

                try:
                    df_bars, df_factors = future.result()
                    if df_bars is None or (hasattr(df_bars, "empty") and df_bars.empty):
                        log.info("no_trade", code=code, n=f"{completed_count}/{total_codes}")
                        no_trade_codes.append(code)
                    else:
                        with db_session() as db:
                            self._bar_w.upsert_single(db, code, df_bars, effective_start, end_date)
                            self._factor_w.upsert_single(db, code, df_factors, effective_start, end_date)
                        log.info("fallback_ok", code=code, n=f"{completed_count}/{total_codes}")
                except Exception as e:
                    log.error("fallback_failed", code=code, error=str(e))
                    error_codes.append(code)

                if task_id:
                    self._report(task_id, completed_count, total_codes, f"Fallback: {code}")

        return error_codes, no_trade_codes

    # ================================================================
    #  单只股票拉取（纯网络 IO）
    # ================================================================

    def _fetch_single(self, code, short_code, start_date, end_date,
                      bs_source_fn, ak_source):
        """拉取单只股票行情 + 因子，返回 (df_bars, df_factors)"""
        df_bars = None
        df_factors = None
        bs_source = None  # 按需求值，整个函数内最多求值一次
        _bs_resolved = False

        def _resolve_bs():
            nonlocal bs_source, _bs_resolved
            if not _bs_resolved:
                bs_source = bs_source_fn() if callable(bs_source_fn) else bs_source_fn
                _bs_resolved = True
            return bs_source

        # ---- 行情 ----
        _bars_api_error = False  # 区分"停牌返回空"与"API 故障抛异常"

        # Tushare 优先
        try:
            df_bars = self._ts.get_stock_history(short_code, start_date, end_date, adjust="qfq")
        except Exception as e:
            _bars_api_error = True
            log.warning("tushare_bars_failed", code=short_code, error=str(e))

        # AkShare fallback（HTTP 无状态，比 Baostock 稳定）
        if (df_bars is None or (hasattr(df_bars, "empty") and df_bars.empty)) and ak_source:
            for attempt in range(2):
                try:
                    df_bars = ak_source.get_stock_history(short_code, start_date, end_date)
                    if df_bars is not None and not df_bars.empty:
                        break
                except Exception as e:
                    _bars_api_error = True
                    log.warning("akshare_bars_failed", code=short_code, error=str(e))
                    if attempt < 1:
                        time.sleep(1.0 * (attempt + 1))

        # Baostock fallback：仅在 API 故障时尝试，停牌（正常返回空）不触发
        if (df_bars is None or (hasattr(df_bars, "empty") and df_bars.empty)) and _bars_api_error:
            if _resolve_bs():
                try:
                    df_bars = bs_source.get_stock_history(short_code, start_date, end_date)
                except Exception as e:
                    log.warning("baostock_bars_failed", code=short_code, error=str(e))

        # ---- 因子 ----
        _factors_api_error = False
        start_dt = start_date.replace("-", "")
        end_dt = end_date.replace("-", "")

        try:
            import data_sources.tushare_source as tushare_module

            @tushare_module.with_tushare_retry(max_retries=1, delay=1.0)
            def _fetch_daily_basic():
                return self._ts.pro.daily_basic(
                    ts_code=self._ts._format_ts_code(short_code),
                    start_date=start_dt, end_date=end_dt,
                )

            df_factors = _fetch_daily_basic()
            if df_factors is not None and not df_factors.empty:
                df_factors = df_factors.rename(columns={"ts_code": "code", "trade_date": "trade_date_str"})
                df_factors["code"] = code
                df_factors["trade_date"] = pd.to_datetime(df_factors["trade_date_str"]).dt.strftime("%Y-%m-%d")
        except Exception as e:
            _factors_api_error = True
            log.warning("tushare_factors_failed", code=short_code, error=str(e))
            df_factors = None

        # Baostock 因子 fallback：仅在 API 故障时尝试
        if (df_factors is None or (hasattr(df_factors, "empty") and df_factors.empty)) and _factors_api_error:
            if _resolve_bs():
                try:
                    import baostock as bs
                    from utils.asset_type import to_bs_code
                    bs_code = to_bs_code(short_code)
                    rs = bs.query_history_k_data_plus(
                        bs_code,
                        fields="date,code,peTTM,pbMRQ,psTTM,turn,isST",
                        start_date=start_date, end_date=end_date,
                        frequency="d", adjustflag="3",
                    )
                    rows = []
                    while rs.error_code == "0" and rs.next():
                        rows.append(rs.get_row_data())
                    if rows:
                        df_bs = pd.DataFrame(rows, columns=rs.fields)
                        df_factors = pd.DataFrame({
                            "trade_date": df_bs["date"],
                            "pe_ttm": pd.to_numeric(df_bs["peTTM"], errors="coerce"),
                            "pb": pd.to_numeric(df_bs["pbMRQ"], errors="coerce"),
                            "ps_ttm": pd.to_numeric(df_bs["psTTM"], errors="coerce"),
                            "turnover_rate": pd.to_numeric(df_bs["turn"], errors="coerce"),
                        })
                        df_factors["code"] = code
                except Exception as e:
                    log.warning("baostock_factors_failed", code=short_code, error=str(e))

        time.sleep(0.5)
        return df_bars, df_factors

    # ================================================================
    #  工具方法
    # ================================================================

    def _get_trade_dates(self, start_date: str, end_date: str) -> list:
        try:
            import data_sources.tushare_source as tushare_module

            @tushare_module.with_tushare_retry(max_retries=2, delay=1.0)
            def _fetch():
                return self._ts.pro.trade_cal(
                    start_date=start_date.replace("-", ""),
                    end_date=end_date.replace("-", ""),
                    is_open="1",
                )

            df = _fetch()
            if df is not None and not df.empty:
                return sorted(df["cal_date"].tolist())
        except Exception as e:
            log.error("trade_cal_failed", error=str(e))
        return []

    @staticmethod
    def _init_baostock():
        try:
            from data_sources.baostock_source import BaostockSource
            src = BaostockSource()
            BaostockSource._login()  # 单例登录，已登录则直接返回
            return src
        except Exception as e:
            log.warning("baostock_init_failed", error=str(e))
            return None

    @staticmethod
    def _init_akshare():
        try:
            from data_sources.akshare_source import AkShareSource
            return AkShareSource()
        except Exception as e:
            log.warning("akshare_init_failed", error=str(e))
            return None

    @staticmethod
    def _report(task_id: str, current: int, total: int, message: str):
        try:
            from utils.task_store import task_store, TaskStatus
            progress = round(current / total * 100) if total > 0 else 0
            task_store.update_task(task_id, TaskStatus.RUNNING, result={
                "progress": progress, "current": current, "total": total, "message": message,
            })
        except Exception as e:
            log.warning("task_report_failed", task_id=task_id, error=str(e))
