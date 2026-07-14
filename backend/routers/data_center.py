"""
数据中心路由
===========
提供数据同步触发、状态查询、全量同步等功能。

端点一览：
  POST /sync_full      → 全链路同步（5 阶段）
  GET  /task/{id}      → 查询任务状态
  GET  /status         → 数仓各表落盘状态 + 水位信息
"""

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Any
from sqlalchemy import func, text
from core.database import db_session
from models.quant_data import StockBasicInfo
from jobs.data_sync_service import DataSyncService
from jobs.signal_job import generate_daily_signals
import structlog
log = structlog.get_logger("data_center")

# 惰性单例，避免模块加载时就实例化
_service = None
def _get_service():
    global _service
    if _service is None:
        _service = DataSyncService()
    return _service


def run_full_sync(start_date, end_date, mode, task_id=None, custom_codes=None, force_refill=False, scope=None):
    _get_service().full_sync(start_date, end_date, mode, task_id, custom_codes, force_refill, scope=scope)

def get_daily_signals(date=None, top_n=10, exclude_st=True, custom_weights=None):
    """读取最新一期的每日信号。custom_weights 不为空时从全量快照中按自定义权重重排。"""
    import json
    from datetime import date as _date_cls
    from core.database import db_session
    from models.quant_data import FactorSnapshot, StockBasicInfo as SBI, StockDailyBar
    from sqlalchemy import func as sqlfunc

    # 归一化日期格式 → YYYY-MM-DD（兼容 YYYYMMDD 输入）
    if date:
        try:
            clean = date.replace("-", "")
            date = f"{clean[:4]}-{clean[4:6]}-{clean[6:8]}"
            _date_cls.fromisoformat(date)  # 校验合法性
        except (ValueError, IndexError):
            date = None  # 格式非法，回退到最新

    with db_session() as db:
        # 自动回退到最近有信号的交易日（周末/节假日/未同步时）
        latest = db.query(sqlfunc.max(FactorSnapshot.trade_date)).scalar()
        if not latest:
            return {"date": None, "signals": []}
        if not date or str(latest) > date:
            date = str(latest)
        else:
            # 传入日期可能无数据（周末等），回退到 <= date 的最近一天
            actual = db.query(sqlfunc.max(FactorSnapshot.trade_date)).filter(
                FactorSnapshot.trade_date <= date
            ).scalar()
            date = str(actual) if actual else str(latest)

        query = db.query(FactorSnapshot, SBI.name, SBI.industry, StockDailyBar.close, StockDailyBar.pct_chg).outerjoin(
            SBI, FactorSnapshot.code == SBI.code
        ).outerjoin(
            StockDailyBar,
            (FactorSnapshot.code == StockDailyBar.code) & (FactorSnapshot.trade_date == StockDailyBar.trade_date)
        ).filter(
            FactorSnapshot.trade_date == date,
            FactorSnapshot.strategy_type == "signal",
            # 排除北交所（4/8/9开头），流动性差不适合信号推荐
            ~FactorSnapshot.code.like("4%"),
            ~FactorSnapshot.code.like("8%"),
            ~FactorSnapshot.code.like("9%"),
        )
        # 读取时后过滤 ST（即使 snapshot 里有，前端也不展示）
        # 注意：name 为 NULL 时 contains 返回 NULL，需用 or_ 兜底
        if exclude_st:
            from sqlalchemy import or_
            query = query.filter(or_(~SBI.name.contains("ST"), SBI.name.is_(None)))
        # 排除退市股（Tushare list_status 可能延迟，名字兜底）
        query = query.filter(or_(~SBI.name.contains("退市"), SBI.name.is_(None)))

        # 自定义权重：读取全量快照，Python 侧重算 composite 后取 top_n
        if custom_weights:
            rows = query.all()
            signals = []
            w_keys = [k for k, v in custom_weights.items() if v and v > 0]
            w_total = sum(custom_weights.get(k, 0) for k in w_keys)
            for r, name, industry, close, pct_chg in rows:
                factors = {}
                if r.factors_json:
                    try:
                        factors = json.loads(r.factors_json)
                    except Exception as e:
                        log.warning("factors_json_parse_error", code=r.code, error=str(e)[:50])
                # 用自定义权重重算 composite
                if w_total > 0:
                    weighted = sum((factors.get(k, 0) or 0) * custom_weights[k] for k in w_keys)
                    composite = weighted / w_total
                else:
                    composite = r.composite or 0
                signals.append({
                    "code": r.code, "name": name or "",
                    "rank": 0,
                    "composite": round(composite, 3),
                    "factors": factors,
                    "close": round(close, 2) if close is not None else None,
                    "pct_chg": round(pct_chg, 2) if pct_chg is not None else None,
                    "industry": industry or "",
                })
            # 按新 composite 降序排序，赋排名，取 top_n
            signals.sort(key=lambda x: x["composite"], reverse=True)
            for i, s in enumerate(signals[:top_n], 1):
                s["rank"] = i
            return {"date": date, "signals": signals[:top_n]}

        # 默认权重：直接用预计算的 rank 排序
        rows = query.order_by(FactorSnapshot.rank).limit(top_n).all()

        signals = []
        for r, name, industry, close, pct_chg in rows:
            factors = {}
            if r.factors_json:
                try:
                    factors = json.loads(r.factors_json)
                except Exception as _e:
                    log.debug("factors_json_parse_error", error=str(_e))
            signals.append({
                "code": r.code, "name": name or "",
                "rank": r.rank,
                "composite": round(r.composite, 3) if r.composite else 0,
                "factors": factors,
                "close": round(close, 2) if close is not None else None,
                "pct_chg": round(pct_chg, 2) if pct_chg is not None else None,
                "industry": industry or "",
            })
        return {"date": date, "signals": signals}



router = APIRouter(prefix="/data_center", tags=["Data Center"])


# ==================== 请求模型 ====================

class SyncRequest(BaseModel):
    start_date: str
    end_date: str
    mode: str = "pool"
    codes: Optional[list] = None
    force_refill: bool = False
    scope: Optional[dict] = None   # {"stock":true, "etf":true, ...}，None=全选




# ==================== 工具函数 ====================

def _check_duplicate(task_type: str):
    """若同类型或其他同步任务正在运行，返回 already_running 响应；否则返回 None"""
    from utils.task_store import task_store
    running_id = task_store.get_running_task(task_type)
    if running_id:
        return {
            "status": "already_running",
            "message": f"任务 {task_type} 已在运行中，请等待完成再重试",
            "task_id": running_id,
        }
    running_type = task_store.has_any_running_sync()
    if running_type:
        return {
            "status": "already_running",
            "message": f"另一个同步任务 [{running_type}] 正在运行，SQLite 不支持并发写入，请等待完成",
        }
    return None


def _bg_sync(task_type: str, fn, background_tasks, *args, **kwargs):
    """
    通用后台同步工厂：去重 → 建任务 → 后台执行。
    自动将 task_id 作为关键字参数传给 fn。
    """
    dup = _check_duplicate(task_type)
    if dup:
        return dup
    from utils.task_store import task_store
    task_id = task_store.create_task(task_type)
    kwargs["task_id"] = task_id
    background_tasks.add_task(fn, *args, **kwargs)
    return {"status": "success", "message": f"{task_type} 已启动", "task_id": task_id}


# ==================== 同步端点 ====================


@router.post("/sync_full")
async def trigger_full_sync(request: SyncRequest, background_tasks: BackgroundTasks):
    """触发全量同步（支持 scope 控制同步范围）"""
    return _bg_sync("full_sync", run_full_sync, background_tasks,
                    request.start_date, request.end_date,
                    request.mode, custom_codes=request.codes,
                    force_refill=request.force_refill,
                    scope=request.scope)




# ==================== 任务状态 ====================

@router.get("/task/{task_id}")
def get_task_status(task_id: str):
    """查询同步任务的实时状态"""
    try:
        from utils.task_store import task_store
        task = task_store.get_task(task_id)
        if not task:
            return {"status": "not_found"}
        return {
            "status": task["status"],
            "result": task.get("result"),
            "error": task.get("error"),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ==================== 数仓状态 ====================

def _scalar(db, query):
    """安全执行 scalar 查询"""
    try:
        return db.execute(query).scalar()
    except Exception as e:
        import structlog
        structlog.get_logger("data_center").warning("scalar_query_failed", error=str(e))
        return None


@router.get("/status")
def get_sync_status():
    """获取数仓各表的落盘状态

    命名约定：品种数量统一用 count，不返回前端未使用的字段。
    所有查询走索引，<0.05s 响应。
    """
    with db_session() as db:
     try:
        result: dict[str, Any] = {}

        # 股票：活跃品种数
        basic_cnt = db.query(func.count(StockBasicInfo.code)).filter(
            StockBasicInfo.is_active == True
        ).scalar() or 0
        result["stock_basic"] = {"count": basic_cnt, "total_stocks": basic_cnt}

        # 行情：最新日期（统一使用 trade_date 工具）
        from utils.trade_date import get_table_latest_date
        last_date = get_table_latest_date("bars")

        # ETF：活跃品种数
        try:
            from models.quant_data import EtfBasicInfo
            etf_cnt = db.query(func.count(EtfBasicInfo.code)).filter(
                EtfBasicInfo.is_active == True  # noqa: E712
            ).scalar() or 0
            result["etf"] = {"count": etf_cnt, "basic_count": etf_cnt}
        except Exception:
            result["etf"] = {"count": 0, "basic_count": 0}

        # 可转债：在市品种数
        try:
            bond_cnt = db.execute(
                text("SELECT COUNT(*) FROM convertible_bond_basic WHERE listed = 1")
            ).scalar() or 0
            result["bond"] = {"count": bond_cnt, "stock_count": bond_cnt}
        except Exception:
            result["bond"] = {"count": 0, "stock_count": 0}

        # 行情更新至
        result["last_update_date"] = last_date

        return result

     except Exception as e:
        return {"error": str(e)}


# ==================== 每日信号 ====================

@router.get("/daily_signals")
def api_daily_signals(date: Optional[str] = None, top_n: int = 10,
                      exclude_st: bool = True, weights: Optional[str] = None):
    """读取最新一期因子打分信号（Top N 股票）。weights 为 JSON 编码的自定义权重。"""
    custom_weights = None
    if weights:
        import json
        try:
            custom_weights = json.loads(weights)
        except Exception as e:
            log.warning("weights_param_parse_error", raw=weights[:100], error=str(e)[:50])
    return get_daily_signals(date, top_n, exclude_st=exclude_st, custom_weights=custom_weights)


@router.post("/trigger_signals")
def api_trigger_signals(
    background_tasks: BackgroundTasks,
    date: Optional[str] = None,
    exclude_st: bool = True,
    min_list_days: int = 60,
):
    """手动触发每日信号计算（走 _bg_sync 统一工厂）"""
    universe_filters = {"exclude_st": exclude_st, "min_list_days": min_list_days}

    def _run(task_id=None, date=None, universe_filters=None):
        from utils.task_store import task_store, TaskStatus
        try:
            if task_id:
                task_store.update_task(task_id, TaskStatus.RUNNING, result={
                    "progress": 10, "message": "正在计算全市场因子评分..."
                })
            result = generate_daily_signals(date, universe_filters=universe_filters)
            count = len(result) if result else 0
            if task_id:
                msg = (f"✅ 信号计算完成，共 {count} 条"
                       if count > 0
                       else "⚠️ 信号计算完成，但无有效结果（可能数据不足或未同步）")
                task_store.update_task(task_id, TaskStatus.COMPLETED, result={
                    "progress": 100,
                    "message": msg,
                    "count": count,
                })
        except Exception as e:
            if task_id:
                task_store.update_task(task_id, TaskStatus.FAILED, error=str(e))
            raise

    return _bg_sync("signal_calc", _run, background_tasks,
                    date=date, universe_filters=universe_filters)

