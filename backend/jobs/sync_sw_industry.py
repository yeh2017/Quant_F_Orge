"""
申万一级行业成分股同步
===========================
数据源：Tushare index_classify(level='L1') + index_member_all(l1_code=xxx)
频率：半年调整一次，90 天内同步过则跳过
策略：增量覆盖——按行业替换，保留已有的其他行业
"""
import structlog
import time
import pandas as pd
from datetime import datetime
from typing import Optional

from core.database import db_session
from models.quant_data import SwIndustry, SyncWatermark

log = structlog.get_logger(__name__)

SKIP_INTERVAL_DAYS = 90  # 水位间隔：90 天内同步过则跳过


def sync_sw_industry(task_id: Optional[str] = None):
    from data_sources.tushare_source import TushareSource
    import data_sources.tushare_source as tushare_module

    # ── 水位检查：90 天内同步过则跳过 ──
    try:
        with db_session() as db:
            wm = db.query(SyncWatermark).filter_by(data_type="sw_industry", mode="any").first()
            if wm and wm.last_sync_date:
                days_since = (datetime.now().date() - wm.last_sync_date).days
                if days_since < SKIP_INTERVAL_DAYS:
                    # 额外检查：行业数是否已满
                    ind_count = db.query(SwIndustry.sw_l1_name).distinct().count()
                    if ind_count >= 31:
                        log.info("sync_sw_industry_skipped", days_since=days_since,
                                 industries=ind_count, next_in=f"{SKIP_INTERVAL_DAYS - days_since}天")
                        return {"status": "skipped", "message": f"90天内已同步过({days_since}天前), {ind_count}/31行业"}
    except Exception as e:
        log.debug("sw_watermark_check_error", error=str(e))

    ts = TushareSource()

    # ── Step 1: 获取申万一级行业列表 ──
    log.info("sync_sw_industry_start")
    _report(task_id, 0, "正在获取申万行业分类...")

    @tushare_module.with_tushare_retry(max_retries=2, delay=1.0)
    def _fetch_classify():
        return ts.pro.index_classify(level='L1', src='SW2021')

    df_cls = _fetch_classify()
    if df_cls is None or df_cls.empty:
        log.error("sync_sw_industry_no_classify")
        return {"status": "error", "message": "无法获取申万行业分类"}

    total = len(df_cls)
    log.info("sync_sw_industry_classify", count=total)

    # ── Step 2: 逐行业拉取成分股 ──
    all_records = []
    success_count = 0
    ip_blocked = False

    for idx, (_, row) in enumerate(df_cls.iterrows()):
        l1_code = row.get("index_code", "")
        l1_name = row.get("industry_name", "")
        if not l1_code or not l1_name:
            continue

        pct = round((idx / total) * 100)
        _report(task_id, pct, f"拉取 {l1_name} ({idx+1}/{total})...")

        @tushare_module.with_tushare_retry(max_retries=2, delay=1.0)
        def _fetch_members(code=l1_code):
            return ts.pro.index_member_all(l1_code=code)

        try:
            df_mem = _fetch_members()
            from settings import SW_INDUSTRY_SLEEP
            time.sleep(SW_INDUSTRY_SLEEP)
        except Exception as e:
            err_str = str(e)
            if any(kw in err_str for kw in ("IP", "ip", "超限", "白名单")):
                log.warning("sync_sw_industry_ip_blocked", l1=l1_name)
                ip_blocked = True
                break
            log.warning("sync_sw_industry_member_fail", l1=l1_name, error=err_str)
            continue

        if df_mem is None or df_mem.empty:
            log.warning("sync_sw_industry_member_empty", l1=l1_name)
            continue

        batch = 0
        for _, m in df_mem.iterrows():
            stock_code = m.get("ts_code") or m.get("con_code", "")
            if not stock_code:
                continue
            out_date = m.get("out_date", None)
            if pd.notna(out_date) and str(out_date).strip():
                continue
            all_records.append({
                "code": stock_code,
                "sw_l1_code": l1_code,
                "sw_l1_name": l1_name,
                "in_date": str(m.get("in_date", "")) if pd.notna(m.get("in_date")) else None,
                "out_date": None,
            })
            batch += 1

        success_count += 1
        log.info("sync_sw_industry_progress", l1=l1_name, kept=batch,
                 total_so_far=len(all_records), progress=f"{success_count}/{total}")

    # ── Step 3: 去重 + 增量写入 ──
    if not all_records:
        log.error("sync_sw_industry_no_records")
        _report(task_id, 100, "❌ 未获取到任何成分股")
        return {"status": "error", "message": "未获取到任何成分股"}

    _report(task_id, 95, f"写入数据库({len(all_records)}条)...")

    with db_session() as db:
        # 按 code 去重
        seen = set()
        unique_records = []
        for r in all_records:
            if r["code"] not in seen:
                seen.add(r["code"])
                unique_records.append(r)

        # 增量覆盖：只替换本次拉取的行业
        fetched_industries = set(r["sw_l1_code"] for r in unique_records)
        db.query(SwIndustry).filter(
            SwIndustry.sw_l1_code.in_(fetched_industries)
        ).delete(synchronize_session=False)
        db.bulk_insert_mappings(SwIndustry, unique_records)
        total_industries = db.query(SwIndustry.sw_l1_name).distinct().count()

    # ── Step 4: 写入水位 ──
    if not ip_blocked and success_count >= 31:
        _write_watermark()

    msg = f"本次 {success_count} 个行业({len(unique_records)}只), 累计 {total_industries}/31"
    if ip_blocked:
        msg += "（IP限制，再次同步可补全）"

    _report(task_id, 100, f"✅ 申万行业: {msg}")
    log.info("sync_sw_industry_done", total=len(unique_records),
             industries_this=success_count, industries_total=total_industries)
    return {
        "status": "partial" if total_industries < 31 else "ok",
        "total_stocks": len(unique_records),
        "industries_done": total_industries,
        "industries_total": 31,
        "message": msg,
    }


def _report(task_id, pct, message):
    """进度上报"""
    if not task_id:
        return
    try:
        from utils.task_store import task_store
        task_store.update_task(task_id, "running", result={
            "progress": pct, "message": message,
        })
    except Exception:
        pass


def _write_watermark():
    """写入同步水位"""
    try:
        with db_session() as db:
            wm = db.query(SyncWatermark).filter_by(data_type="sw_industry", mode="any").first()
            if wm:
                wm.last_sync_date = datetime.now().date()
                wm.status = "success"
            else:
                db.add(SyncWatermark(
                    data_type="sw_industry",
                    mode="any",
                    last_sync_date=datetime.now().date(),
                    status="success",
                ))
    except Exception as e:
        log.warning("sw_watermark_write_error", error=str(e))
