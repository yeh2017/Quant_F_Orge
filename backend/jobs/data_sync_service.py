"""
数据同步门面服务
===============
对外暴露 3 个入口，对内组合 Writers / Scheduler / Checker 等组件。
替代原 data_fetcher.py 中散落的过程式函数。
"""

import time
import traceback
import structlog
import pandas as pd
from typing import Optional, List

from core.database import db_session
from models.quant_data import SyncWatermark
from data_sources.tushare_source import TushareSource

from jobs.stock_pool_resolver import StockPoolResolver
from jobs.incremental_checker import IncrementalChecker
from jobs.sync_scheduler import SyncScheduler
from jobs.writers import BarWriter, FactorWriter, FinancialWriter, SentimentWriter

log = structlog.get_logger("data_sync")



class DataSyncService:
    """
    数据同步门面类。

    对外 3 个入口（与 Router 1:1 对应）:
      - sync_bars_and_factors(): 同步行情 + 因子
      - full_sync(): 全量同步（列表 + 行情 + 因子 + 财务）
      - sync_stock_basic(): 同步股票静态信息
    """

    def __init__(self):
        self._ts = TushareSource()
        self._pool_resolver = StockPoolResolver(self._ts)
        self._inc_checker = IncrementalChecker()
        self._bar_w = BarWriter()
        self._factor_w = FactorWriter()
        self._fin_w = FinancialWriter()
        self._sent_w = SentimentWriter()
        self._scheduler = SyncScheduler(self._ts, self._bar_w, self._factor_w)

    # ================================================================
    #  公共：end_date 交易日校正
    # ================================================================

    def _resolve_end_date(self, end_date: str) -> str:
        """将 end_date 校正到 <= today 的最近交易日（委托给 trade_date 模块）"""
        from utils.trade_date import resolve_end_date
        return resolve_end_date(end_date)

    # ================================================================
    #  入口 1: 同步行情 + 因子
    # ================================================================

    def sync_bars_and_factors(
        self,
        start_date: str,
        end_date: str,
        mode: str,
        task_id: Optional[str] = None,
        custom_codes: Optional[List[str]] = None,
        force_refill: bool = False,     # True = 忽略水位，强制从 start_date 补历史
    ):
        from datetime import timedelta

        end_date = self._resolve_end_date(end_date)

        _effective_start = start_date
        if force_refill:
            # 强制补历史：忽略水位，直接用用户传入的 start_date
            log.info("force_refill_mode", start_date=start_date, mode=mode)
        else:
            try:
                with db_session() as db:
                    wm = db.query(SyncWatermark).filter_by(
                        data_type="bars", mode=mode
                    ).first()
                    if wm and wm.last_sync_date:
                        wm_next = (wm.last_sync_date + timedelta(days=1)).strftime("%Y-%m-%d")
                        if wm_next > start_date:
                            _effective_start = wm_next
                            log.info("watermark_advance", mode=mode,
                                     from_date=start_date, to_date=_effective_start)
            except Exception as _e:
                log.debug("watermark_read_error", error=str(_e))

        # ── 边界保护：水位已推进到 end_date 之后 ──
        # 但水位可能超前（上次同步写了水位但实际数据未写入），
        # 用 DB 实际最大日期 + 覆盖率二次确认，防止数据缺口被忽略
        if _effective_start >= end_date:
            try:
                from sqlalchemy import text as _text
                with db_session() as db:
                    row = db.execute(_text(
                        "SELECT MAX(trade_date) FROM stock_daily_bars "
                        "WHERE code IN (SELECT code FROM stock_basic_info)"
                    )).fetchone()
                    db_max = str(row[0]) if row and row[0] else None

                    # 覆盖率校验：最新日期的股票数 vs 活跃股票总数
                    # 防止 pool 模式少量记录骗过 all 模式边界保护
                    coverage_ok = True
                    if db_max and mode == "all":
                        bar_cnt = db.execute(_text(
                            "SELECT COUNT(DISTINCT code) FROM stock_daily_bars "
                            f"WHERE trade_date = '{db_max}'"
                        )).scalar() or 0
                        basic_cnt = db.execute(_text(
                            "SELECT COUNT(*) FROM stock_basic_info WHERE is_active = 1"
                        )).scalar() or 1
                        coverage = bar_cnt / basic_cnt
                        if coverage < 0.5:
                            log.warning(
                                "sparse_max_date_detected",
                                db_max=db_max, bar_cnt=bar_cnt,
                                basic_cnt=basic_cnt, coverage=f"{coverage:.1%}",
                                hint="最新日期覆盖率过低（可能是 pool 模式残留），强制重新同步"
                            )
                            coverage_ok = False

                if db_max and db_max < end_date:
                    # 水位超前但 DB 数据不足 → 从 DB 最大日期 +1 重新同步
                    db_next = (pd.to_datetime(db_max) + timedelta(days=1)).strftime("%Y-%m-%d")
                    log.warning(
                        "watermark_ahead_of_db",
                        watermark=_effective_start, db_max=db_max,
                        end_date=end_date, resync_from=db_next,
                        hint="水位超前，DB实际数据不足，自动修正同步起点"
                    )
                    _effective_start = db_next  # 修正：从实际数据断点继续
                elif not coverage_ok:
                    # 最新日期覆盖率不足（pool 残留） → 从该日重新同步
                    _effective_start = db_max
                    log.warning(
                        "coverage_resync",
                        resync_from=_effective_start, end_date=end_date,
                        hint="覆盖率不足，从最新稀疏日期重新同步"
                    )
                else:
                    log.info(
                        "already_up_to_date",
                        effective_start=_effective_start,
                        end_date=end_date,
                        db_max=db_max,
                        mode=mode,
                        reason="watermark >= end_date and DB data confirmed",
                    )
                    if task_id:
                        self._report(task_id, 0, 0, "所有数据已是最新（水位超过结束日期）")
                    return
            except Exception as e:
                log.warning("watermark_db_check_failed", error=str(e))
                # 检查失败时不跳过，继续尝试同步

        log.info("sync_start", start=_effective_start, end=end_date, mode=mode,
                 user_requested_start=start_date)
        t_start = time.time()

        try:
            target_codes = self._pool_resolver.resolve(mode, custom_codes)
            total_codes = len(target_codes)

            # 增量检测（force_refill 时跳过，直接全量从 _effective_start 拉）
            if force_refill:
                # 强制补历史：所有 code 从 _effective_start 开始，不做增量优化
                inc_starts = {code: _effective_start for code in target_codes}
                max_dates = {}
                need_sync = list(target_codes)
                truly_skipped = []
                batch_start = _effective_start
                log.info("force_refill_skip_incremental_check",
                         codes=len(need_sync), from_date=_effective_start)
            else:
                inc_starts, max_dates = self._inc_checker.check(target_codes, _effective_start, end_date)
                truly_skipped, need_sync, batch_start = self._inc_checker.split(
                    target_codes, inc_starts, max_dates, _effective_start
                )

            if not need_sync:
                log.info("all_up_to_date", total=total_codes)
                if task_id:
                    self._report(task_id, total_codes, total_codes, "所有股票已是最新")
                return

            log.info("need_sync", count=len(need_sync), batch_start=batch_start)

            # 调度
            sync_result = self._scheduler.run(
                need_sync=need_sync,
                batch_start=batch_start,
                end_date=end_date,
                start_date=_effective_start,
                incremental_starts=inc_starts,
                task_id=task_id,
                total_codes=total_codes,
                already_done=len(truly_skipped),
            )

            # 成功后写行情水位：用 DB 实际最新 trade_date，而不是 end_date
            # 原因：end_date 可能是节假日/补班周六/当日数据未发布，
            #       实际写入的最新日期可能早于 end_date
            try:
                from sqlalchemy import text as _text2
                with db_session() as db:
                    r = db.execute(_text2(
                        "SELECT MAX(trade_date) FROM stock_daily_bars "
                        "WHERE code IN (SELECT code FROM stock_basic_info)"
                    )).fetchone()
                    actual_max = str(r[0]) if r and r[0] else end_date
            except Exception as _e:
                log.debug("actual_max_query_error", error=str(_e))
                actual_max = end_date   # 查询失败时退回 end_date

            self._write_watermark("bars", mode, actual_max, t_start, "success")
            log.info("sync_done", duration=round(time.time()-t_start, 1),
                     watermark_date=actual_max,
                     failed=sync_result.get("failed", 0))

            # 将失败/未交易信息附加到 sync_result
            sync_result["rows"] = sync_result.get("synced", 0)
            if sync_result.get("no_trade", 0) > 0:
                log.info("sync_no_trade",
                         no_trade=sync_result["no_trade"],
                         sample=", ".join(sync_result.get("no_trade_codes", [])[:5]))
            if sync_result.get("failed", 0) > 0:
                codes_str = ", ".join(sync_result["failed_codes"][:10])
                log.warning("sync_partial_failure",
                            failed=sync_result["failed"],
                            sample=codes_str)

            # 信号生成已移至 full_sync step 9 统一处理，此处不再重复调用

            return sync_result

        except Exception as e:
            log.error("sync_fatal", error=str(e))
            self._write_watermark("bars", mode, end_date, t_start, "failed", str(e))
            traceback.print_exc()

    # ================================================================
    #  入口 2: 全量同步
    # ================================================================

    def full_sync(
        self,
        start_date: str,
        end_date: str,
        mode: str,
        task_id: Optional[str] = None,
        custom_codes: Optional[List[str]] = None,
        force_refill: bool = False,
        scope: Optional[dict] = None,
    ):
        """
        全量同步入口。
        每个阶段封装为 SyncStep，带 weight 用于统一计算进度。
        添加新阶段只需在列表中追加一行。
        """
        from dataclasses import dataclass
        from typing import Callable

        @dataclass
        class SyncStep:
            name: str           # 水位 key，写入 SyncWatermark.data_type
            label: str          # 中文显示名称
            weight: int         # 进度权重（各步和应为 100）
            fn: Callable        # 实际执行函数
            skip_if: bool = False  # 为 True 时跳过本步
            min_points: int = 0    # 所需最低 Tushare 积分，0=无限制

        end_date = self._resolve_end_date(end_date)

        log.info("full_sync_start", mode=mode, start=start_date, end=end_date)
        t_total = time.time()

        # 解析股票池（Phase 2-4 共用）
        target_codes = self._pool_resolver.resolve(mode, custom_codes)

        # scope 控制：前端勾选哪些数据类别同步，scope=None 表示全选（向后兼容）
        def _scope_skip(key):
            return False if scope is None else not scope.get(key, True)

        # 定义各阶段（添加新阶段只需在此追加一行）
        steps = [
            SyncStep(
                name="stock_basic", label="股票列表", weight=5,
                fn=self.sync_stock_basic,
                skip_if=(mode == "pool") or _scope_skip("stock"),
            ),
            SyncStep(
                name="bars_factors", label="行情+因子", weight=35,
                fn=lambda: self.sync_bars_and_factors(
                    start_date, end_date, mode, None, custom_codes, force_refill),
                skip_if=_scope_skip("stock"),
            ),
            SyncStep(
                name="etf_basic", label="ETF列表", weight=1,
                fn=self._sync_etf_basic_and_sw,
                skip_if=_scope_skip("etf"),
            ),
            SyncStep(
                name="etf_daily", label="ETF日线", weight=4,
                fn=lambda: self._sync_etf_daily(start_date, end_date, force_refill),
                skip_if=_scope_skip("etf") or (
                    (not force_refill) and self._is_up_to_date("etf_daily")),
            ),
            SyncStep(
                name="etf_nav_share", label="ETF净值+份额", weight=2,
                fn=lambda: self._sync_etf_nav_share(
                    start_date if force_refill else None,
                    end_date if force_refill else None),
                skip_if=_scope_skip("etf") or (
                    (not force_refill) and self._is_up_to_date("etf_nav_share")),
            ),
            SyncStep(
                name="bond_basic", label="可转债列表", weight=1,
                fn=self._sync_bond_basic_only,
                skip_if=_scope_skip("bond"),
                min_points=5000,
            ),
            SyncStep(
                name="bond_history", label="可转债行情", weight=2,
                fn=lambda: self._sync_bond_history_only(start_date, end_date, force_refill),
                skip_if=_scope_skip("bond") or (
                    (not force_refill) and self._is_up_to_date("bond_history")),
                min_points=5000,
            ),
            SyncStep(
                name="bond_factor", label="可转债因子", weight=2,
                fn=self._sync_bond_factor_only,
                skip_if=_scope_skip("bond"),
                min_points=5000,  # 依赖 bond_basic 数据，积分门槛一致
            ),
            SyncStep(
                name="financials", label="财务数据", weight=25,
                fn=lambda: self._sync_financial(target_codes, None, force_refill=force_refill),
                skip_if=_scope_skip("financial") or (
                    (not force_refill) and self._should_skip_financial(mode)),
            ),
            SyncStep(
                name="moneyflow", label="资金流向", weight=3,
                fn=lambda: self._sync_moneyflow(target_codes, start_date, end_date, force_refill),
                skip_if=_scope_skip("moneyflow") or (
                    (not force_refill) and self._is_up_to_date("moneyflow")),
                min_points=5000,
            ),
            SyncStep(
                name="shareholder", label="股东户数", weight=13,
                fn=lambda: self._sync_shareholder(target_codes, force_refill),
                skip_if=_scope_skip("financial") or (
                    (not force_refill) and self._should_skip_shareholder(mode)),
                min_points=600,
            ),
            SyncStep(
                name="industry_index", label="行业指数", weight=2,
                fn=lambda: self._sync_industry_index(start_date, end_date),
                skip_if=_scope_skip("industry") or (
                    (not force_refill) and self._is_up_to_date("industry_index")),
            ),
            SyncStep(
                name="index_weight", label="指数成分权重", weight=2,
                fn=lambda: self._sync_index_weight(),
                skip_if=_scope_skip("stock") or (
                    (not force_refill) and self._is_up_to_date("index_weight")),
                min_points=2000,
            ),
            SyncStep(
                name="margin", label="融资融券", weight=1,
                fn=lambda: self._sync_margin(start_date, end_date, force_refill),
                skip_if=_scope_skip("margin") or (
                    (not force_refill) and self._is_db_up_to_date("stock_margin_data")),
                min_points=5000,
            ),
            SyncStep(
                name="events", label="事件数据(大宗/解禁/龙虎榜)", weight=1,
                fn=lambda: self._sync_events(start_date, end_date, force_refill),
                skip_if=_scope_skip("events") or (
                    (not force_refill) and self._is_events_up_to_date()),
                min_points=5000,
            ),
            SyncStep(
                name="signals", label="因子评分+每日信号", weight=5,
                fn=lambda: self._generate_signals(),
                skip_if=_scope_skip("stock"),
            ),
            SyncStep(
                name="cleanup", label="清理旧数据", weight=5,
                fn=self._cleanup_old_data,
            ),
        ]

        # 运行时读取积分等级（设置页修改后立即生效）
        from settings import get_tushare_points
        user_points = get_tushare_points()

        # 进度权重只计算实际执行的步骤（排除 scope 跳过 + 积分不足），避免进度条跳跃
        def _will_run(s):
            if s.skip_if:
                return False
            if s.min_points > 0 and user_points < s.min_points:
                return False
            return True

        total_weight = sum(s.weight for s in steps if _will_run(s)) or 1
        done_weight = 0

        try:
            step_reports = []  # 收集每步结果

            for idx, step in enumerate(steps):
                if step.skip_if:
                    log.info("phase_skipped", phase=step.name, mode=mode)
                    step_reports.append(f"⏭ {step.label}: 跳过")
                    done_weight += step.weight
                    continue

                # 积分不足时自动跳过，避免静默失败
                if step.min_points > 0 and user_points < step.min_points:
                    log.info("phase_skipped_points", phase=step.name,
                             required=step.min_points, current=user_points)
                    step_reports.append(
                        f"⏭ {step.label}: 需≥{step.min_points}积分")
                    done_weight += step.weight
                    continue

                # 进度报告：阶段开始
                pct_start = round(done_weight / total_weight * 100)
                if task_id:
                    self._report(task_id, pct_start, 100,
                                 f"阶段 {idx+1}/{len(steps)}: 正在同步{step.label}...",
                                 extra={"steps": list(step_reports)})

                t0 = time.time()
                try:
                    result = step.fn()
                    duration = round(time.time() - t0, 1)
                    # 尝试从返回值提取行数
                    row_info = ""
                    fail_info = ""
                    if isinstance(result, dict):
                        rows = result.get("rows") or result.get("total") or result.get("count")
                        if rows is not None:
                            row_info = f" ({rows:,}条)"
                        # 数据关键步骤返回 0 条时告警（可能是 Tushare 积分不足）
                        if rows == 0 and step.name in ("bars_factors", "financials", "moneyflow"):
                            log.warning("sync_zero_rows", phase=step.name,
                                        hint="Tushare 积分不足或 API 限频，请检查")
                            fail_info += ", ⚠️0条数据(积分不足?)"
                        # 失败与未交易分类
                        failed = result.get("failed", 0)
                        no_trade = result.get("no_trade", 0)
                        if no_trade > 0:
                            fail_info += f", ⏸{no_trade}只未交易(停牌)"
                        if failed > 0:
                            sample = ", ".join(result.get("failed_codes", [])[:5])
                            fail_info += f", ⚠️{failed}只失败: {sample}"
                    elif isinstance(result, (int, float)) and result > 0:
                        row_info = f" ({int(result):,}条)"
                    step_reports.append(f"✅ {step.label}: {duration}s{row_info}{fail_info}")
                except Exception as step_err:
                    duration = round(time.time() - t0, 1)
                    step_reports.append(f"❌ {step.label}: {str(step_err)[:60]}")
                    log.error("phase_error", phase=step.name, error=str(step_err))

                done_weight += step.weight
                pct_done = round(done_weight / total_weight * 100)

                log.info("phase_done", phase=step.name, mode=mode,
                         codes_count=len(target_codes), duration=duration)
                if task_id:
                    self._report(task_id, pct_done, 100,
                                 f"阶段 {idx+1}/{len(steps)}: {step.label}完成",
                                 extra={"steps": list(step_reports)})

            total_dur = round(time.time() - t_total, 1)
            log.info("full_sync_done", total_duration=total_dur, mode=mode,
                     codes_count=len(target_codes))
            self._write_watermark("full_sync", mode, end_date, t_total, "success")

            # ── 数据完整性校验（委托 integrity_check 模块）──
            from jobs.integrity_check import run_integrity_check, run_quality_check
            run_integrity_check(step_reports)
            run_quality_check(step_reports)

            # 构建汇总消息
            has_error = any(r.startswith("❌") for r in step_reports)
            summary_icon = "⚠️" if has_error else "✅"
            summary_msg = (
                f"{summary_icon} 全量同步完成 (耗时 {total_dur}s)\n"
                + " | ".join(step_reports)
            )

            if task_id:
                try:
                    from utils.task_store import task_store, TaskStatus
                    task_store.update_task(task_id, TaskStatus.COMPLETED, result={
                        "progress": 100,
                        "message": summary_msg,
                        "duration_seconds": total_dur,
                        "steps": step_reports,
                    })
                except Exception as _e:
                    log.debug("suppressed_error", error=str(_e))

        except Exception as e:
            log.error("full_sync_fatal", error=str(e), mode=mode)
            self._write_watermark("full_sync", mode, end_date, t_total, "failed", str(e))
            traceback.print_exc()
            if task_id:
                try:
                    from utils.task_store import task_store, TaskStatus
                    task_store.update_task(task_id, TaskStatus.FAILED, error=str(e))
                except Exception as _e:
                    log.debug("suppressed_error", error=str(_e))

    # ================================================================
    #  入口 3: 同步股票静态信息
    # ================================================================

    def sync_stock_basic(self, task_id: Optional[str] = None) -> int:
        log.info("sync_basic_start")
        try:
            import data_sources.tushare_source as tushare_module
            from sqlalchemy import text as sa_text
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert
            from models.quant_data import StockBasicInfo

            # ── 第一步：拉在市股票 ──
            @tushare_module.with_tushare_retry(max_retries=2, delay=1.0)
            def _fetch_listed():
                return self._ts.pro.stock_basic(
                    exchange="", list_status="L",
                    fields="ts_code,name,industry,market,list_date",
                )

            df_listed = _fetch_listed()
            if df_listed is None or df_listed.empty:
                log.warning("basic_empty")
                return 0

            records = []
            for _, row in df_listed.iterrows():
                raw_date = pd.to_datetime(row.get("list_date"), format="%Y%m%d", errors="coerce")
                list_date_str = raw_date.strftime("%Y-%m-%d") if pd.notna(raw_date) else None
                records.append({
                    "code": row["ts_code"],
                    "name": row.get("name", ""),
                    "industry": row.get("industry", ""),
                    "market": row.get("market", ""),
                    "list_date": list_date_str,
                    "delist_date": None,
                    "is_active": True,
                })

            # ── 第二步：拉退市股票（补 delist_date，回测存活偏差校正用）──
            try:
                @tushare_module.with_tushare_retry(max_retries=2, delay=1.0)
                def _fetch_delisted():
                    return self._ts.pro.stock_basic(
                        exchange="", list_status="D",
                        fields="ts_code,name,industry,market,list_date,delist_date",
                    )

                df_delisted = _fetch_delisted()
                if df_delisted is not None and not df_delisted.empty:
                    for _, row in df_delisted.iterrows():
                        raw_list = pd.to_datetime(row.get("list_date"), format="%Y%m%d", errors="coerce")
                        raw_delist = pd.to_datetime(row.get("delist_date"), format="%Y%m%d", errors="coerce")
                        records.append({
                            "code": row["ts_code"],
                            "name": row.get("name", ""),
                            "industry": row.get("industry", ""),
                            "market": row.get("market", ""),
                            "list_date": raw_list.strftime("%Y-%m-%d") if pd.notna(raw_list) else None,
                            "delist_date": raw_delist.strftime("%Y-%m-%d") if pd.notna(raw_delist) else None,
                            "is_active": False,
                        })
                    log.info("sync_basic_delisted_fetched", count=len(df_delisted))
            except Exception as e:
                # 退市股拉取失败不影响主流程
                log.warning("sync_basic_delisted_failed", error=str(e))

            from settings import WRITE_BATCH_SIZE
            BATCH = WRITE_BATCH_SIZE
            with db_session() as db:
                # 先标记所有股票为 inactive（退市股保留记录，不删除）
                db.execute(sa_text("UPDATE stock_basic_info SET is_active = 0"))
                db.flush()
                # Upsert：在市股标 is_active=True，退市股标 is_active=False + delist_date
                for i in range(0, len(records), BATCH):
                    chunk = records[i: i + BATCH]
                    stmt = sqlite_insert(StockBasicInfo).values(chunk)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["code"],
                        set_={
                            "name": stmt.excluded.name,
                            "industry": stmt.excluded.industry,
                            "market": stmt.excluded.market,
                            "list_date": stmt.excluded.list_date,
                            "delist_date": stmt.excluded.delist_date,
                            "is_active": stmt.excluded.is_active,
                        },
                    )
                    db.execute(stmt)
                db.flush()

            active_count = sum(1 for r in records if r["is_active"])
            delisted_count = len(records) - active_count
            log.info("sync_basic_done", active=active_count, delisted=delisted_count)
            return active_count

        except Exception as e:
            log.error("sync_basic_failed", error=str(e))
            return 0
    
    # ================================================================
    #  财务数据同步（委托 sync_financial 模块）
    # ================================================================

    def _sync_financial(self, codes: List[str], task_id: Optional[str] = None,
                        force_refill: bool = False):
        from jobs.sync_financial import sync_financial
        sync_financial(self._ts, self._fin_w, codes, task_id, force_refill)

    def _fetch_financial(self, code: str):
        from jobs.sync_financial import _fetch_financial
        return _fetch_financial(self._ts, code)



    # ================================================================
    #  情绪因子同步（拆分为 3 个独立阶段，各自有独立水位和跳过间隔）
    # ================================================================

    def _sync_moneyflow(self, codes: list, start_date: str, end_date: str, force_refill: bool = False):
        """资金流向（每日更新）"""
        from jobs.sync_sentiment import sync_moneyflow_only
        return sync_moneyflow_only(self._ts, self._sent_w, codes, start_date, end_date, force_refill)


    def _sync_shareholder(self, codes: list, force_refill: bool = False):
        """股东户数（季度更新）"""
        from jobs.sync_sentiment import sync_shareholder_only
        sync_shareholder_only(self._ts, self._sent_w, codes, force_refill)

    # ================================================================
    #  ETF 日线同步
    # ================================================================


    def _sync_etf_basic_and_sw(self):
        """ETF 列表重建 + 申万行业（始终执行，无水位控制，耗时<2s）"""
        from jobs.sync_etf import sync_etf_basic
        from jobs.sync_sw_industry import sync_sw_industry
        count = sync_etf_basic()
        sync_sw_industry()
        return count

    def _sync_etf_daily(self, start_date: str, end_date: str, force_refill: bool = False):
        """ETF 日线增量同步（受水位控制）"""
        from jobs.sync_etf import sync_etf_daily
        s = start_date.replace("-", "")
        e = end_date.replace("-", "")
        return sync_etf_daily(start_date=s, end_date=e, force_refill=force_refill)

    def _sync_etf_nav_share(self, start_date=None, end_date=None):
        """ETF 净值+份额快照同步。日常存当天，force_refill 时按日期范围补历史。"""
        from jobs.sync_etf_nav import sync_etf_nav_share
        return sync_etf_nav_share(start_date=start_date, end_date=end_date)

    def _sync_bond_basic_only(self):
        """可转债列表刷新（始终执行，标记到期债+新债入库，耗时<2s）"""
        from jobs.sync_bond import sync_bond_basic
        sync_bond_basic()

    def _sync_bond_history_only(self, start_date: str, end_date: str, force_refill: bool = False):
        """可转债行情增量同步（受水位控制）"""
        from jobs.sync_bond import sync_bond_history
        sync_bond_history(start_date.replace("-", ""), end_date.replace("-", ""), force_refill=force_refill)

    def _sync_bond_factor_only(self):
        """可转债因子快照（始终执行，内部 upsert 去重）"""
        from jobs.sync_bond import sync_bond_factor
        sync_bond_factor()

    # ================================================================
    #  行业指数同步
    # ================================================================

    def _sync_industry_index(self, start_date: str, end_date: str):
        from jobs.sync_industry import sync_industry_index
        return sync_industry_index(self._ts, start_date, end_date)

    def _sync_index_weight(self):
        from jobs.sync_index_weight import sync_index_weight
        return sync_index_weight(self._ts)

    def _sync_margin(self, start_date: str = None, end_date: str = None, force_refill: bool = False):
        from jobs.sync_margin import sync_margin
        return sync_margin(self._ts, start_date, end_date, force_refill)

    def _sync_events(self, start_date: str, end_date: str, force_refill: bool = False):
        from jobs.sync_events import sync_events
        return sync_events(self._ts, start_date, end_date, force_refill)

    # ================================================================
    #  每日信号生成
    # ================================================================

    def _generate_signals(self):
        """生成每日因子信号，日期由 signal_job 从 DB 自动获取最新行情日期"""
        from jobs.signal_job import generate_daily_signals
        generate_daily_signals()

    # ================================================================
    #  数据清理（委托 sync_base 模块）
    # ================================================================

    def _cleanup_old_data(self):
        from jobs.sync_base import cleanup_old_data
        cleanup_old_data()

    # ================================================================
    #  工具（委托 sync_base 模块）
    # ================================================================

    # 水位 mode 映射：查询时必须与 write_watermark 写入的 mode 完全一致
    _WATERMARK_MODE = {
        "financials": "any", "moneyflow": "any",
        "shareholder": "any", "events": "any",
        "etf_daily": "all", "bond_history": "all", "industry_index": "all",
    }

    def _is_up_to_date(self, data_type: str) -> bool:
        """水位日期 >= 最新交易日 → 已是最新，跳过。用于日频数据。"""
        from jobs.sync_base import is_up_to_date
        mode = self._WATERMARK_MODE.get(data_type, "all")
        return is_up_to_date(data_type, mode)

    def _is_db_up_to_date(self, table_name: str, date_col: str = "trade_date",
                          extra_where: str = "") -> bool:
        """基于 DB 实际最大日期判断是否最新（不信任水位）。

        专用于 margin/events 等有 T+1 延迟的模块。
        extra_where: 可选 SQL 条件片段（如 "AND event_type IN (...)"），
                     用于混合表中区分不同数据类型。
        """
        try:
            from sqlalchemy import text
            from utils.trade_date import resolve_end_date
            with db_session() as db:
                sql = f"SELECT MAX(DATE({date_col})) FROM {table_name}"
                if extra_where:
                    sql += f" WHERE 1=1 {extra_where}"
                r = db.execute(text(sql)).scalar()
                if not r:
                    return False  # 表为空，需要同步
                db_max = str(r).replace("-", "")[:8]
                latest_td = resolve_end_date().replace("-", "")[:8]
                up_to_date = db_max >= latest_td
                if up_to_date:
                    log.info("db_up_to_date", table=table_name,
                             db_max=db_max, latest=latest_td)
                return up_to_date
        except Exception as e:
            log.debug("db_up_to_date_check_failed", table=table_name, error=str(e))
            return False  # 查询失败时不跳过

    def _is_events_up_to_date(self) -> bool:
        """事件同步专用：三类事件(大宗/解禁/龙虎榜)全部最新才跳过。

        取各类型 MAX(publish_time) 的 MIN — 任一类缺失则返回 False。
        避免部分类型失败被跳过后永远补不回。
        """
        try:
            from sqlalchemy import text
            from utils.trade_date import resolve_end_date
            with db_session() as db:
                r = db.execute(text("""
                    SELECT MIN(type_max) FROM (
                        SELECT MAX(DATE(publish_time)) as type_max
                        FROM stock_news
                        WHERE event_type IN ('大宗交易','解禁','龙虎榜')
                        GROUP BY event_type
                    )
                """)).scalar()
                if not r:
                    return False
                db_min = str(r).replace("-", "")[:8]
                latest_td = resolve_end_date().replace("-", "")[:8]
                up_to_date = db_min >= latest_td
                if up_to_date:
                    log.info("events_up_to_date", db_min=db_min, latest=latest_td)
                return up_to_date
        except Exception as e:
            log.debug("events_up_to_date_failed", error=str(e))
            return False

    def _should_skip(self, data_type: str, mode: str, min_interval_hours: float = 20) -> bool:
        """时钟间隔跳过。仅用于低频数据（财务/分析师/股东）。"""
        from jobs.sync_base import should_skip
        effective_mode = self._WATERMARK_MODE.get(data_type, mode)
        return should_skip(data_type, effective_mode, min_interval_hours)

    def _should_skip_financial(self, mode: str) -> bool:
        """财报季才拉：1/4/7/8/10月拉（间隔7天），其余月份跳过"""
        from datetime import datetime
        month = datetime.now().month
        # 财报季：年报1-4月，一季报4月，中报7-8月，三季报10月
        earnings_months = {1, 2, 3, 4, 7, 8, 10}
        if month not in earnings_months:
            log.info("skip_financial_non_earnings_season", month=month)
            return True
        # 财报季内，7 天拉一次（查 mode="any" 由 _should_skip 处理）
        return self._should_skip("financials", mode, min_interval_hours=168)

    def _should_skip_shareholder(self, mode: str) -> bool:
        """股东户数跟财报季：财报季内 7 天拉一次，非财报季跳过"""
        from datetime import datetime
        month = datetime.now().month
        earnings_months = {1, 2, 3, 4, 7, 8, 10}
        if month not in earnings_months:
            log.info("skip_shareholder_non_earnings_season", month=month)
            return True
        # 财报季内，7 天拉一次（与财务数据一致）
        return self._should_skip("shareholder", mode, min_interval_hours=168)

    @staticmethod
    def _report(task_id: str, current: int, total: int, message: str, extra: dict = None):
        from jobs.sync_base import report_progress
        report_progress(task_id, current, total, message, extra)

    @staticmethod
    def _write_watermark(data_type: str, mode: str, last_sync_date: str,
                         t_start: float, status: str, error_msg: str = None):
        from jobs.sync_base import write_watermark
        write_watermark(data_type, mode, last_sync_date, t_start, status, error_msg)

    # ── 可转债同步（委托给 sync_bond 模块）──

    def sync_bond_basic(self, task_id: str = None):
        from jobs.sync_bond import sync_bond_basic
        sync_bond_basic(task_id=task_id)

    def sync_bond_history(self, start_date: str = None,
                          end_date: str = None, task_id: str = None,
                          force_refill: bool = False):
        from jobs.sync_bond import sync_bond_history
        sync_bond_history(start_date=start_date, end_date=end_date,
                          task_id=task_id, force_refill=force_refill)


    def sync_bond_factor(self, trade_date: str = None, task_id: str = None):
        from jobs.sync_bond import sync_bond_factor
        sync_bond_factor(trade_date=trade_date, task_id=task_id)
