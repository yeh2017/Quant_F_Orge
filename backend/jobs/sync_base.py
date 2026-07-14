"""
同步公共工具
===========
进度上报 / 水位管理 / 跳过检测 / 数据清理
"""

import time
import structlog
from datetime import datetime

from core.database import db_session
from models.quant_data import SyncWatermark

log = structlog.get_logger("sync_base")


def report_progress(task_id: str, current: int, total: int, message: str, extra: dict = None):
    """向 task_store 上报进度"""
    try:
        from utils.task_store import task_store, TaskStatus
        progress = round(current / total * 100) if total > 0 else 0
        result = {
            "progress": progress, "current": current, "total": total, "message": message,
        }
        if extra:
            result.update(extra)
        task_store.update_task(task_id, TaskStatus.RUNNING, result=result)
    except Exception:
        pass


def write_watermark(data_type: str, mode: str, last_sync_date: str,
                    t_start: float, status: str, error_msg: str = None):
    """向 sync_watermark 表写入一条同步水位记录"""
    try:
        import pandas as pd
        done_at = datetime.now()
        duration = round(time.time() - t_start, 1)
        try:
            parsed = pd.to_datetime(last_sync_date, errors="coerce")
            sync_date = None if pd.isna(parsed) else parsed.date()
        except Exception:
            sync_date = None

        with db_session() as db:
            existing = db.query(SyncWatermark).filter_by(
                data_type=data_type, mode=mode
            ).first()
            if existing:
                # 核心规则：只有 success 才推进水位日期
                # empty/failed 只更新元数据，保留上次成功的日期
                if status == "success" and sync_date:
                    existing.last_sync_date = sync_date
                existing.last_done_at = done_at
                existing.duration_seconds = duration
                existing.status = status
                existing.error_msg = error_msg
            else:
                db.add(SyncWatermark(
                    data_type=data_type,
                    mode=mode,
                    last_sync_date=sync_date if status == "success" else None,
                    last_run_at=done_at,
                    last_done_at=done_at,
                    duration_seconds=duration,
                    status=status,
                    error_msg=error_msg,
                ))
    except Exception as e:
        log.warning("watermark_write_failed", data_type=data_type, error=str(e))


def should_skip(data_type: str, mode: str, min_interval_hours: float = 20) -> bool:
    """查询 sync_watermark，若上次同步距现在不足 min_interval_hours 小时则跳过"""
    try:
        with db_session() as db:
            wm = db.query(SyncWatermark).filter_by(
                data_type=data_type, mode=mode,
            ).first()
            if wm and wm.last_done_at:
                # 上次失败 → 不跳过，下次同步时立即重试
                if wm.status == "failed":
                    log.info("phase_retry_after_failure", data_type=data_type)
                    return False
                elapsed_hours = (datetime.now() - wm.last_done_at).total_seconds() / 3600
                if elapsed_hours < min_interval_hours:
                    log.info("phase_skip_by_watermark",
                             data_type=data_type,
                             elapsed_h=round(elapsed_hours, 1),
                             threshold_h=min_interval_hours)
                    return True
    except Exception as e:
        log.debug("watermark_check_failed", error=str(e))
    return False


def is_up_to_date(data_type: str, mode: str = "all") -> bool:
    """基于水位判断数据是否已同步到最新交易日（替代时钟判断）。

    逻辑：水位日期 >= 今天的 resolve_end_date → 已是最新，跳过。
    比 should_skip(min_interval_hours=24) 更精确：
      - 14:00 同步后 16:00 再同步 → 水位=昨天 < 今天 → 不跳过 ✅
      - 国庆连续点同步 → 水位=节前最后交易日 = resolve后的最新交易日 → 跳过 ✅
    """
    wm_date = read_watermark(data_type, mode)
    if not wm_date:
        return False  # 从未同步过，不跳过
    try:
        from utils.trade_date import resolve_end_date
        latest_td = resolve_end_date().replace("-", "")[:8]
        up_to_date = wm_date >= latest_td
        if up_to_date:
            log.info("phase_skip_up_to_date",
                     data_type=data_type, watermark=wm_date, latest=latest_td)
        return up_to_date
    except Exception as e:
        log.debug("is_up_to_date_check_failed", error=str(e))
        return False


def cleanup_old_data():
    """清理旧数据（委托 cleanup_job 统一入口，保留 7 年）"""
    from jobs.cleanup_job import cleanup_database
    cleanup_database()


# ==================== 统一水位读写 ====================

def read_watermark(data_type: str, mode: str = "all") -> str | None:
    """
    从 SyncWatermark 表读取上次成功同步的日期（显式水位）。

    返回 YYYYMMDD 格式字符串，若无记录则返回 None。
    write_watermark 保证 last_sync_date 只在 success 时推进，
    因此此处不过滤 status —— 日期本身就代表最后成功的水位。
    """
    try:
        with db_session() as db:
            wm = db.query(SyncWatermark).filter_by(
                data_type=data_type, mode=mode,
            ).first()
            if wm and wm.last_sync_date:
                return str(wm.last_sync_date).replace("-", "")[:8]
    except Exception as e:
        log.debug("read_watermark_failed", data_type=data_type, error=str(e))
    return None


def calc_next_start(data_type: str, mode: str, fallback_start: str) -> str:
    """
    计算下一次同步的起始日期。

    逻辑：读显式水位 → +1天 → 与 fallback_start 取较晚者。
    返回 YYYYMMDD 格式。
    """
    from datetime import timedelta
    wm_date = read_watermark(data_type, mode)
    if wm_date:
        try:
            next_day = (datetime.strptime(wm_date, "%Y%m%d")
                        + timedelta(days=1)).strftime("%Y%m%d")
            if next_day > fallback_start:
                log.info("watermark_advance",
                         data_type=data_type, wm=wm_date, next=next_day)
                return next_day
        except (ValueError, TypeError):
            pass
    return fallback_start


